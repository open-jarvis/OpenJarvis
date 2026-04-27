#!/usr/bin/env python3
"""Step 2: Seed feedback on every per-cell traces.db produced by step 1 (and 6).

Discovery order:
  1. ``--db PATH``            single explicit db
  2. ``$OPENJARVIS_HOME``     single db at ``$OPENJARVIS_HOME/traces.db``
  3. matrix ``[paths]``        walk ``baseline_results_dir`` + ``distilled_results_dir``
                               for ``**/traces.db`` (the per-cell layout that the
                               eval harness writes; see jarvis_agent.py:70-73).
  4. fallback                  ``~/.openjarvis/traces.db``

Cross-DB dedup. The same ``trace_id`` can legitimately appear in more than one
db (e.g. an old global ``~/.openjarvis/traces.db`` plus a fresh per-cell copy).
Step 2 builds a single catalog keyed by ``trace_id`` *before* judging, so:

  - each unique ``trace_id`` is judged at most once (no double API calls)
  - if any copy already has feedback, its score is propagated to the others
    (no API call, no risk of divergent scores)
  - feedback is written back to *every* db that holds that ``trace_id``, so
    each per-cell db stays self-contained

Merge. After judging, every per-cell db is dedup-merged into
``~/.openjarvis/traces.db`` (INSERT OR IGNORE, keyed by ``trace_id``) so step 3
(the M1 teacher) reads from one unified set. Skipped when running in single-db
mode (``--db`` / ``OPENJARVIS_HOME``).

Idempotent — safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import CloudEngine
from openjarvis.traces.store import TraceStore

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MATRIX = HERE / "pipeline_matrix.toml"
FALLBACK_HOME = Path.home() / ".openjarvis"
GLOBAL_DB = FALLBACK_HOME / "traces.db"

MODEL = "claude-sonnet-4-6"
MAX_WORKERS = 8

JUDGE_PROMPT = """\
You are evaluating whether an AI agent successfully completed its assigned task.

Assign a SCORE from the set {{0.2, 0.4, 0.6, 0.8}} using this rubric:

- 0.8 = Clean success. Task completed correctly. Minor stylistic issues don't affect correctness.
- 0.6 = Partial. Real progress made but the answer has real gaps — missed requirement, incomplete output, recovered from errors but final result imperfect.
- 0.4 = Poor. Some progress but the result is clearly incomplete, wrong, or the agent got mostly stuck.
- 0.2 = Failure. Agent crashed, got stuck in a loop, gave up, hit a budget/poll/token limit before finishing, or produced no usable result.

IMPORTANT: Do not trust the agent's own self-assessment. Agents often narrate "I am stuck" or "I hit an error" — those are failure signals. Agents sometimes claim success when the actual output is incomplete — look at the concrete result, not the rhetoric.

TASK QUERY (first 1200 chars):
<<<
{query}
>>>

AGENT FINAL RESULT (first 2500 chars):
<<<
{result_head}
>>>
{tail_section}
Respond in EXACTLY this format, nothing else:
SCORE=<one of 0.2, 0.4, 0.6, 0.8>
REASON=<one brief sentence>
"""


SCORE_RE = re.compile(r"SCORE\s*=\s*(0?\.[2468])", re.IGNORECASE)
REASON_RE = re.compile(r"REASON\s*=\s*(.+?)\s*$", re.IGNORECASE | re.DOTALL)


# ── DB discovery ────────────────────────────────────────────────────────────


@dataclass
class Discovery:
    dbs: list[Path]
    single_db_mode: bool  # True when --db or OPENJARVIS_HOME selected one db


def discover_dbs(matrix_path: Path, explicit: Path | None) -> Discovery:
    """Return the list of traces.db files step 2 should operate on, plus a
    flag for whether we're in single-db mode (skips the global merge)."""
    if explicit is not None:
        return Discovery(dbs=[explicit], single_db_mode=True)

    home_override = os.environ.get("OPENJARVIS_HOME")
    if home_override:
        return Discovery(dbs=[Path(home_override) / "traces.db"], single_db_mode=True)

    dbs: list[Path] = []
    if matrix_path.exists():
        matrix = tomllib.loads(matrix_path.read_text())
        paths = matrix.get("paths", {})
        for key in ("baseline_results_dir", "distilled_results_dir"):
            rel = paths.get(key)
            if not rel:
                continue
            root = (REPO_ROOT / rel).resolve()
            if root.exists():
                dbs.extend(sorted(root.rglob("traces.db")))

    # Always include the global db if it already has data — its rows might be
    # the only ones with feedback (older runs), and we want to dedup against it.
    if GLOBAL_DB.exists():
        dbs.append(GLOBAL_DB)

    if dbs:
        seen: set[Path] = set()
        unique: list[Path] = []
        for d in dbs:
            try:
                r = d.resolve()
            except OSError:
                continue
            if r not in seen:
                seen.add(r)
                unique.append(d)
        return Discovery(dbs=unique, single_db_mode=False)

    print(
        f"No per-cell traces.db found under matrix results dirs; "
        f"falling back to {GLOBAL_DB}"
    )
    return Discovery(dbs=[GLOBAL_DB], single_db_mode=True)


# ── Judge ───────────────────────────────────────────────────────────────────


def build_prompt(query: str, result: str) -> str:
    q = (query or "")[:1200]
    head = (result or "")[:2500]
    if result and len(result) > 3000:
        tail = f"\nAGENT FINAL RESULT (last 500 chars):\n<<<\n{result[-500:]}\n>>>\n"
    else:
        tail = ""
    return JUDGE_PROMPT.format(query=q, result_head=head, tail_section=tail)


def judge_one(ce: CloudEngine, trace_id: str, query: str, result: str) -> dict:
    prompt = build_prompt(query, result)
    t0 = time.time()
    try:
        resp = ce.generate(
            messages=[Message(role=Role.USER, content=prompt)],
            model=MODEL,
            max_tokens=150,
            temperature=0.0,
        )
        content = resp.get("content", "") or ""
        cost = resp.get("cost_usd", 0.0) or 0.0
        usage = resp.get("usage", {}) or {}
        in_tok = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
        out_tok = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)

        m = SCORE_RE.search(content)
        score = float(m.group(1)) if m else None
        mr = REASON_RE.search(content)
        reason = mr.group(1).strip() if mr else "(parse failed)"

        return {
            "trace_id": trace_id,
            "score": score,
            "reason": reason,
            "raw": content,
            "cost": cost,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "elapsed": time.time() - t0,
            "judged_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "error": None,
        }
    except Exception as e:
        return {
            "trace_id": trace_id,
            "score": None,
            "reason": None,
            "raw": None,
            "cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "elapsed": time.time() - t0,
            "judged_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "error": f"{type(e).__name__}: {e}",
        }


# ── Cross-DB catalog ────────────────────────────────────────────────────────


@dataclass
class TraceRecord:
    """One unique trace_id, possibly present in multiple dbs."""

    trace_id: str
    query: str
    result: str
    existing_feedback: float | None  # any non-null score found across dbs
    db_paths: list[Path] = field(default_factory=list)


def build_catalog(db_paths: list[Path]) -> tuple[dict[str, TraceRecord], int]:
    """Read every (trace_id, query, result, feedback) row across all dbs and
    fold into a single map keyed by trace_id.

    Returns ``(catalog, n_total_rows)``. ``n_total_rows`` counts duplicates
    so the summary can report the dedup ratio.
    """
    catalog: dict[str, TraceRecord] = {}
    n_rows = 0
    for db_path in db_paths:
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
        except sqlite3.OperationalError as e:
            print(f"WARN: could not open {db_path}: {e}", file=sys.stderr)
            continue
        try:
            rows = conn.execute(
                "SELECT trace_id, query, result, feedback FROM traces"
            ).fetchall()
        except sqlite3.OperationalError as e:
            print(f"WARN: could not read {db_path}: {e}", file=sys.stderr)
            conn.close()
            continue
        for r in rows:
            n_rows += 1
            tid = r["trace_id"]
            rec = catalog.get(tid)
            if rec is None:
                catalog[tid] = TraceRecord(
                    trace_id=tid,
                    query=r["query"] or "",
                    result=r["result"] or "",
                    existing_feedback=r["feedback"],
                    db_paths=[db_path],
                )
                continue

            rec.db_paths.append(db_path)
            # First non-null score wins. Warn if scores differ — they
            # shouldn't, since step 2 is the only writer.
            if r["feedback"] is not None:
                if rec.existing_feedback is None:
                    rec.existing_feedback = r["feedback"]
                elif rec.existing_feedback != r["feedback"]:
                    print(
                        f"WARN: trace {tid[:12]} has divergent scores "
                        f"({rec.existing_feedback} vs {r['feedback']}) "
                        f"across dbs; keeping the first.",
                        file=sys.stderr,
                    )
            # If the first db had empty query/result, fill in from a later one.
            if not rec.query and r["query"]:
                rec.query = r["query"]
            if not rec.result and r["result"]:
                rec.result = r["result"]
        conn.close()
    return catalog, n_rows


# ── Writeback ───────────────────────────────────────────────────────────────


def write_feedback(db_paths: list[Path], trace_id: str, score: float) -> int:
    """Write ``feedback = score`` to every db that contains ``trace_id``.

    Returns the total number of rows updated across dbs.
    """
    total = 0
    for db_path in db_paths:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.OperationalError as e:
            print(
                f"WARN: could not open {db_path} for writeback: {e}",
                file=sys.stderr,
            )
            continue
        try:
            cur = conn.execute(
                "UPDATE traces SET feedback = ? WHERE trace_id = ?",
                (score, trace_id),
            )
            conn.commit()
            total += cur.rowcount
        finally:
            conn.close()
    return total


def append_log(log_fp, log_lock: threading.Lock, payload: dict) -> None:
    with log_lock:
        log_fp.write(json.dumps(payload) + "\n")
        log_fp.flush()


# ── Merge into the global DB ────────────────────────────────────────────────


def merge_into_global(per_cell_dbs: list[Path]) -> tuple[int, int]:
    """ATTACH each per-cell db to ``~/.openjarvis/traces.db`` and dedup-merge.

    The traces table has ``trace_id TEXT UNIQUE``, so ``INSERT OR IGNORE``
    handles row-level dedup. The trace_steps table has no UNIQUE constraint,
    so we only insert steps for trace_ids that aren't already present in
    main (otherwise re-runs would multiply step rows).

    Returns ``(n_traces_inserted, n_feedback_propagated)``.
    """
    FALLBACK_HOME.mkdir(parents=True, exist_ok=True)
    # Initialise the global db via TraceStore so the schema (incl. FTS
    # triggers) is in place before we INSERT.
    TraceStore(GLOBAL_DB).close()

    global_resolved = GLOBAL_DB.resolve()
    conn = sqlite3.connect(str(GLOBAL_DB))
    n_traces = 0
    n_feedback = 0
    try:
        for db_path in per_cell_dbs:
            try:
                if db_path.resolve() == global_resolved:
                    continue
            except OSError:
                continue
            conn.execute(f"ATTACH DATABASE '{db_path}' AS src")
            try:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO main.traces ("
                    "  trace_id, query, agent, model, engine, result, outcome,"
                    "  feedback, started_at, ended_at, total_tokens,"
                    "  total_latency_seconds, metadata, messages"
                    ") "
                    "SELECT trace_id, query, agent, model, engine, result, outcome,"
                    "       feedback, started_at, ended_at, total_tokens,"
                    "       total_latency_seconds, metadata, messages "
                    "FROM src.traces"
                )
                n_traces += cur.rowcount
                # Back-fill feedback for traces that exist in main but lacked
                # a score (the source has one).
                cur = conn.execute(
                    "UPDATE main.traces "
                    "SET feedback = ("
                    "  SELECT feedback FROM src.traces "
                    "  WHERE src.traces.trace_id = main.traces.trace_id"
                    ") "
                    "WHERE main.traces.feedback IS NULL "
                    "  AND main.traces.trace_id IN ("
                    "    SELECT trace_id FROM src.traces WHERE feedback IS NOT NULL"
                    "  )"
                )
                n_feedback += cur.rowcount
                # Steps: only for trace_ids not already in main.
                conn.execute(
                    "INSERT INTO main.trace_steps ("
                    "  trace_id, step_index, step_type, timestamp,"
                    "  duration_seconds, input, output, metadata"
                    ") "
                    "SELECT trace_id, step_index, step_type, timestamp,"
                    "       duration_seconds, input, output, metadata "
                    "FROM src.trace_steps "
                    "WHERE trace_id NOT IN (SELECT trace_id FROM main.trace_steps)"
                )
                conn.commit()
            finally:
                conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    return n_traces, n_feedback


# ── Entry point ─────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Run against exactly this traces.db; bypasses matrix discovery.",
    )
    p.add_argument(
        "--no-merge",
        action="store_true",
        help=f"Skip merging per-cell dbs into {GLOBAL_DB}.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List the dbs that would be processed and exit.",
    )
    args = p.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    discovery = discover_dbs(args.matrix, args.db)
    dbs = discovery.dbs

    print(f"Will process {len(dbs)} db(s):")
    for d in dbs:
        try:
            size_mb = d.stat().st_size / (1024 * 1024)
            size_str = f"  ({size_mb:.1f} MB)"
        except OSError:
            size_str = "  (missing)"
        try:
            rel = d.relative_to(REPO_ROOT)
        except ValueError:
            rel = d
        print(f"  {rel}{size_str}")

    catalog, n_rows = build_catalog(dbs)
    n_unique = len(catalog)
    n_already_scored = sum(
        1 for r in catalog.values() if r.existing_feedback is not None
    )
    n_in_multiple = sum(1 for r in catalog.values() if len(r.db_paths) > 1)
    to_judge = [r for r in catalog.values() if r.existing_feedback is None]
    to_propagate = [
        r
        for r in catalog.values()
        if r.existing_feedback is not None and len(r.db_paths) > 1
    ]

    print()
    print(
        f"Catalog: {n_unique} unique trace_id(s) "
        f"({n_rows} rows across {len(dbs)} db(s))"
    )
    print(f"  duplicates collapsed    : {n_rows - n_unique}")
    print(f"  appearing in >1 db      : {n_in_multiple}")
    print(f"  already scored anywhere : {n_already_scored}")
    print(f"  to judge (new)          : {len(to_judge)}")
    print(f"  to propagate (existing) : {len(to_propagate)}")
    print(f"  parallelism             : {MAX_WORKERS} workers")

    if args.dry_run:
        return 0

    # ── Phase 1: propagate already-known scores (no API calls) ──────────────
    n_prop_writes = 0
    for rec in to_propagate:
        n_prop_writes += write_feedback(
            rec.db_paths, rec.trace_id, float(rec.existing_feedback)
        )
    if n_prop_writes:
        print(f"\nPropagated existing scores → {n_prop_writes} row(s) updated.")

    # ── Phase 2: judge unscored unique trace_ids ────────────────────────────
    errors = 0
    score_counts: dict = {}
    total_cost = 0.0

    if to_judge:
        ce = CloudEngine()

        # One log file per source-db directory, like before. Pick the dir of
        # the first db each trace_id lives in — keeps the log near the data.
        log_handles: dict[Path, "tuple[object, threading.Lock]"] = {}

        def get_log(db_path: Path):
            log_path = db_path.parent / "a1_feedback_log.jsonl"
            handle = log_handles.get(log_path)
            if handle is None:
                fp = open(log_path, "a", encoding="utf-8")
                fp.write(
                    json.dumps(
                        {
                            "_run_started": datetime.utcnow().isoformat(
                                timespec="seconds"
                            )
                            + "Z",
                            "model": MODEL,
                            "workers": MAX_WORKERS,
                            "to_judge_total": len(to_judge),
                        }
                    )
                    + "\n"
                )
                fp.flush()
                handle = (fp, threading.Lock())
                log_handles[log_path] = handle
            return handle

        done = 0
        t_start = time.time()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(judge_one, ce, r.trace_id, r.query, r.result): r
                for r in to_judge
            }
            for fut in as_completed(futures):
                rec = futures[fut]
                res = fut.result()

                if res["score"] is not None and res["error"] is None:
                    write_feedback(rec.db_paths, rec.trace_id, float(res["score"]))
                else:
                    errors += 1

                fp, lock = get_log(rec.db_paths[0])
                append_log(fp, lock, {**res, "n_dbs": len(rec.db_paths)})

                total_cost += res["cost"] or 0.0
                done += 1
                score_counts[res["score"]] = score_counts.get(res["score"], 0) + 1

                if done % 50 == 0 or res["error"]:
                    elapsed = time.time() - t_start
                    rate = done / max(0.001, elapsed)
                    eta = (len(to_judge) - done) / max(0.001, rate)
                    tag = "ERR " if res["error"] else "    "
                    print(
                        f"{tag}[{done:4}/{len(to_judge)}] score={res['score']} "
                        f"cost=${total_cost:.3f} "
                        f"rate={rate:.1f}/s eta={eta:.0f}s "
                        f"errors={errors}"
                    )
                    if res["error"]:
                        print(f"    ERROR on {rec.trace_id[:12]}: {res['error']}")

        for fp, _ in log_handles.values():
            fp.close()

        elapsed = time.time() - t_start
        print(f"\n{'=' * 60}")
        print(f"Judging complete in {elapsed:.1f}s ({elapsed / 60:.1f}min)")
        print(f"Unique traces judged: {done}")
        print(f"Errors:               {errors}/{len(to_judge)}")
        print(f"Total cost:           ${total_cost:.4f}")
        if done:
            print("Score distribution:")
            for k in sorted(score_counts.keys(), key=lambda x: (x is None, x)):
                v = score_counts[k]
                pct = 100 * v / done
                label = {
                    0.2: "failure",
                    0.4: "poor",
                    0.6: "partial",
                    0.8: "clean",
                    None: "ERROR",
                }.get(k, "?")
                print(f"  {k} ({label}): {v} ({pct:.1f}%)")
    else:
        print("\nNo traces need judging.")

    # ── Phase 3: merge per-cell dbs into the global db ──────────────────────
    if not args.no_merge and not discovery.single_db_mode:
        global_resolved = GLOBAL_DB.resolve() if GLOBAL_DB.exists() else None
        per_cell = [
            d for d in dbs if global_resolved is None or d.resolve() != global_resolved
        ]
        if per_cell:
            print()
            print(f"Merging {len(per_cell)} per-cell db(s) → {GLOBAL_DB}")
            n_inserted, n_propagated = merge_into_global(per_cell)
            print(f"  inserted {n_inserted} new trace row(s)")
            print(f"  back-filled feedback on {n_propagated} existing row(s)")

    # ── Final state of the global db (informational) ────────────────────────
    if GLOBAL_DB.exists():
        gconn = sqlite3.connect(str(GLOBAL_DB))
        try:
            total = gconn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
            with_fb = gconn.execute(
                "SELECT COUNT(*) FROM traces WHERE feedback IS NOT NULL"
            ).fetchone()[0]
            above_gate = gconn.execute(
                "SELECT COUNT(*) FROM traces WHERE feedback >= 0.7"
            ).fetchone()[0]
            print()
            print(f"Global db ({GLOBAL_DB}):")
            print(f"  total traces          : {total}")
            print(f"  with feedback         : {with_fb}")
            print(f"  passing 0.7 gate (M1) : {above_gate}")
        finally:
            gconn.close()

    return 0 if errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
