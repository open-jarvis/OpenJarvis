#!/usr/bin/env python3
"""A1: Seed feedback on all traces in the local M1 traces.db.

- Judges each unscored trace with Sonnet 4.6 using the calibration-validated prompt
- Parallelized via ThreadPoolExecutor (8 workers) for I/O-bound API calls
- Writes feedback to local traces.db via TraceStore.update_feedback
- Logs every call to a JSONL audit file
- Idempotent: skips traces that already have feedback (safe to re-run)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import CloudEngine
from openjarvis.traces.store import TraceStore

HOME = Path(os.environ.get("OPENJARVIS_HOME", "/scratch/user/jonsaadfalcon/openjarvis-m1"))
DB = HOME / "traces.db"
LOG = HOME / "a1_feedback_log.jsonl"
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


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    store = TraceStore(DB)
    # Use the TraceStore's connection for the initial read
    conn = store._conn
    conn.row_factory = sqlite3.Row

    # Pull all traces that need scoring
    rows = list(conn.execute(
        "SELECT trace_id, query, result, agent, model FROM traces "
        "WHERE feedback IS NULL"
    ))
    already_scored = conn.execute(
        "SELECT COUNT(*) FROM traces WHERE feedback IS NOT NULL"
    ).fetchone()[0]

    print(f"traces.db: {conn.execute('SELECT COUNT(*) FROM traces').fetchone()[0]} total")
    print(f"  already scored: {already_scored}")
    print(f"  to judge: {len(rows)}")
    print(f"parallelism: {MAX_WORKERS} workers")
    print(f"log: {LOG}")

    if not rows:
        print("Nothing to do.")
        return 0

    ce = CloudEngine()
    write_lock = threading.Lock()
    log_lock = threading.Lock()
    log_fp = open(LOG, "a", encoding="utf-8")

    # Write a header line marking this run
    log_fp.write(json.dumps({
        "_run_started": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "model": MODEL,
        "workers": MAX_WORKERS,
        "to_judge": len(rows),
        "already_scored": already_scored,
    }) + "\n")
    log_fp.flush()

    total_cost = 0.0
    done = 0
    errors = 0
    score_counts: dict = {}
    t_start = time.time()

    def on_result(res: dict) -> None:
        nonlocal total_cost, done, errors
        trace_id = res["trace_id"]

        # Write feedback to DB (if we got a valid score)
        if res["score"] is not None and res["error"] is None:
            with write_lock:
                store.update_feedback(trace_id, res["score"])
                conn.commit()
        else:
            errors += 1

        with log_lock:
            log_fp.write(json.dumps(res) + "\n")
            log_fp.flush()

        total_cost += res["cost"] or 0.0
        done += 1
        score_counts[res["score"]] = score_counts.get(res["score"], 0) + 1

        # Progress every 50 or on error
        if done % 50 == 0 or res["error"]:
            elapsed = time.time() - t_start
            rate = done / max(0.001, elapsed)
            eta = (len(rows) - done) / max(0.001, rate)
            tag = "ERR " if res["error"] else "    "
            print(
                f"{tag}[{done:4}/{len(rows)}] score={res['score']} "
                f"cost=${total_cost:.3f} "
                f"rate={rate:.1f}/s eta={eta:.0f}s "
                f"errors={errors}"
            )
            if res["error"]:
                print(f"    ERROR on {trace_id[:12]}: {res['error']}")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [
            pool.submit(judge_one, ce, r["trace_id"], r["query"] or "", r["result"] or "")
            for r in rows
        ]
        for fut in as_completed(futures):
            res = fut.result()
            on_result(res)

    log_fp.close()

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"A1 COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"Errors: {errors}/{len(rows)}")
    print(f"Score distribution:")
    for k in sorted(score_counts.keys(), key=lambda x: (x is None, x)):
        v = score_counts[k]
        pct = 100 * v / len(rows)
        label = {0.2: "failure", 0.4: "poor", 0.6: "partial", 0.8: "clean", None: "ERROR"}.get(k, "?")
        print(f"  {k} ({label}): {v} ({pct:.1f}%)")

    # Verify by re-counting from DB
    with_fb = conn.execute(
        "SELECT COUNT(*) FROM traces WHERE feedback IS NOT NULL"
    ).fetchone()[0]
    above_gate = conn.execute(
        "SELECT COUNT(*) FROM traces WHERE feedback >= 0.7"
    ).fetchone()[0]
    print(f"\nPost-A1 DB state:")
    print(f"  traces with feedback: {with_fb}")
    print(f"  traces passing 0.7 gate (eligible for personal benchmark): {above_gate}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
