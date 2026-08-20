"""CLI runner for hybrid paradigm experiments.

::

    python -m openjarvis.agents.hybrid.runner --cell minions-gaia-qwen27b-opus-3

Reads a cell definition from ``registry/<method>.toml`` (bundled with this
package or pointed at by ``OPENJARVIS_HYBRID_REGISTRY_DIR``), constructs
the registered agent, loads bench tasks via OpenJarvis's existing dataset
providers, runs every task, scores it, and writes
``<EXPERIMENTS_DIR>/runs/<cell>/results.jsonl`` + ``summary.json``.

The output schema matches ``hybrid-local-cloud-compute/runner.py`` so the
existing rescore / dashboard scripts can read OpenJarvis cells without
modification.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

from openjarvis.agents._stubs import AgentContext, AgentResult
from openjarvis.agents.hybrid._energy import EnergyCollector
from openjarvis.agents.hybrid._prompts import format_prompt as _format_prompt
from openjarvis.core.paths import get_config_dir

PACKAGE_DIR = Path(__file__).parent
DEFAULT_REGISTRY_DIR = PACKAGE_DIR / "registry"
DEFAULT_EXPERIMENTS_DIR = Path(
    os.environ.get(
        "OPENJARVIS_HYBRID_EXPERIMENTS_DIR",
        get_config_dir() / "experiments" / "hybrid",
    )
)
DEFAULT_SUBSETS_DIR = DEFAULT_EXPERIMENTS_DIR / "subsets"
DEFAULT_RUNS_DIR = DEFAULT_EXPERIMENTS_DIR / "runs"

# Hard per-task wall-clock cap. Even when every individual network /
# subprocess call has its own timeout, a pathological chain (SDK retries
# stacking on top of a hung connection, a Modal harness subprocess whose
# grandchildren keep its stdout pipe open, etc.) can leave one task
# blocked indefinitely — and with the runner's ThreadPoolExecutor that
# wedges the whole cell (`as_completed` never advances). SWE-bench tasks
# legitimately run ~15-20 min, so the default cap is 30 min: long enough
# never to abort a healthy task, short enough that a frozen one is
# abandoned and recorded as an error row (which the resume logic re-runs)
# instead of silently killing the process. Override with
# ``OPENJARVIS_HYBRID_TASK_TIMEOUT_S`` (0 / negative disables).
DEFAULT_TASK_TIMEOUT_S = float(
    os.environ.get("OPENJARVIS_HYBRID_TASK_TIMEOUT_S", "1800") or 1800
)


# ---------- Registry ----------

_SWE_BENCHES = {"swebench-verified", "swebench_verified", "swebench"}


def _validate_cells(cells: Dict[str, Dict[str, Any]]) -> None:
    """Catch registry mistakes that would silently degrade behaviour.

    Currently: skillorchestra on a SWE bench MUST have
    ``method_cfg.swe_use_agent_loop = true``. Without the flag,
    skillorchestra.py falls back to a one-shot cloud call even for
    SWE-bench tasks, which is rarely what the experimenter wants and is
    invisible at runtime (Bug 5, 2026-05-15).
    """
    bad: List[str] = []
    for name, cell in cells.items():
        if cell.get("method") != "skillorchestra":
            continue
        if cell.get("bench") not in _SWE_BENCHES:
            continue
        mcfg = cell.get("method_cfg") or {}
        if not bool(mcfg.get("swe_use_agent_loop")):
            bad.append(name)
    if bad:
        raise ValueError(
            "skillorchestra SWE cells missing required "
            "`method_cfg.swe_use_agent_loop = true`: "
            + ", ".join(sorted(bad))
            + ". Without this flag the cell silently falls back to a "
            "one-shot cloud call for SWE-bench tasks."
        )


def load_registry(registry_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Merge every ``<registry_dir>/*.toml``. Cell names must be unique."""
    base = registry_dir or DEFAULT_REGISTRY_DIR
    env_override = os.environ.get("OPENJARVIS_HYBRID_REGISTRY_DIR")
    if env_override:
        base = Path(env_override)
    if not base.is_dir():
        return {}
    cells: Dict[str, Dict[str, Any]] = {}
    for p in sorted(base.glob("*.toml")):
        data = tomllib.loads(p.read_text())
        for name, cell in data.get("cells", {}).items():
            if name in cells:
                raise ValueError(
                    f"duplicate cell {name!r} (already defined before {p.name})"
                )
            cells[name] = cell
    _validate_cells(cells)
    return cells


# ---------- Bench dispatch ----------


def _load_gaia_tasks(n: Optional[int]) -> List[Dict[str, Any]]:
    """GAIA validation. Each task is a dict with `task_id` + `question`."""
    from openjarvis.evals.datasets.gaia import GAIADataset

    ds = GAIADataset()
    ds.load(max_samples=n)
    out: List[Dict[str, Any]] = []
    for rec in ds.iter_records():
        # rec.problem is the formatted question prompt; rec.metadata carries
        # the GAIA-specific fields including any reference answer. Prefer the
        # upstream GAIA `task_id` field (bare uuid) over rec.record_id (which
        # OpenJarvis prefixes with `gaia-`) so subsets keyed by the upstream
        # id round-trip.
        md = rec.metadata or {}
        task_id = md.get("task_id") or rec.record_id
        out.append(
            {
                "task_id": task_id,
                "question": md.get("question", rec.problem),
                "reference": rec.reference,
                "metadata": dict(md),
            }
        )
    return out


def _load_swebench_tasks(n: Optional[int]) -> List[Dict[str, Any]]:
    """SWE-bench-Verified test. Each task carries patch-evaluation fields."""
    from openjarvis.evals.datasets.swebench import SWEBenchDataset

    ds = SWEBenchDataset(variant="verified")
    ds.load(max_samples=n)
    out: List[Dict[str, Any]] = []
    for rec in ds.iter_records():
        md = rec.metadata or {}
        out.append(
            {
                "task_id": md.get("instance_id", rec.record_id),
                "repo": md.get("repo", ""),
                "base_commit": md.get("base_commit", ""),
                "problem_statement": md.get("problem_statement", rec.problem),
                "hints_text": md.get("hints_text", ""),
                "test_patch": md.get("test_patch", ""),
                "FAIL_TO_PASS": md.get("FAIL_TO_PASS", []),
                "PASS_TO_PASS": md.get("PASS_TO_PASS", []),
                "version": md.get("version"),
                "reference": rec.reference,
                "metadata": dict(md),
            }
        )
    return out


def load_tasks(bench: str, n: Optional[int]) -> List[Dict[str, Any]]:
    if bench == "gaia":
        return _load_gaia_tasks(n)
    if bench in ("swebench-verified", "swebench_verified", "swebench"):
        return _load_swebench_tasks(n)
    raise ValueError(f"unknown bench: {bench!r}")


def _load_subset_file(subset_path: str) -> Dict[str, Any]:
    """Resolve a cell's ``subset`` field to a parsed JSON dict.

    Resolution order:
      1. Absolute path → use as-is.
      2. Bare filename / relative path → look up under
         ``<experiments>/subsets/`` (matches where ``make_subset.py``
         writes its output).

    Accepts both list-of-ids and dict-with-task_ids shapes; the legacy
    harness wrote the dict shape and we preserve that. Returns a dict
    with at least a ``task_ids`` list so callers don't have to branch.
    """
    p = Path(subset_path)
    if not p.is_absolute():
        p = DEFAULT_SUBSETS_DIR / p
    if not p.exists():
        raise FileNotFoundError(f"subset file not found: {p}")
    data = json.loads(p.read_text())
    if isinstance(data, list):
        return {"task_ids": list(data)}
    if isinstance(data, dict):
        if "task_ids" not in data:
            raise ValueError(
                f"subset {p.name} has no 'task_ids' field; got keys {list(data.keys())}"
            )
        return data
    raise ValueError(
        f"subset {p.name} must be a list or dict; got {type(data).__name__}"
    )


def _apply_subset(
    tasks: List[Dict[str, Any]],
    subset: Dict[str, Any],
    cell: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Filter ``tasks`` to the subset's task IDs, preserving subset order.

    Hard-errors if the cell's ``n`` doesn't equal ``len(task_ids)`` so a
    typo in the registry can't silently shrink the eval. Also errors if
    any subset ID is missing from the dataset (caller's bench wiring is
    broken).
    """
    ids: List[str] = list(subset["task_ids"])
    cell_n = int(cell["n"])
    if cell_n != len(ids):
        raise ValueError(
            f"subset n={len(ids)} ≠ cell n={cell_n} — refusing to silently "
            "change scope. Fix the registry's `n` to match the subset file."
        )
    if "bench" in subset and subset["bench"] != cell["bench"]:
        raise ValueError(
            f"subset bench={subset['bench']!r} ≠ cell bench={cell['bench']!r}"
        )
    order = {tid: i for i, tid in enumerate(ids)}
    allow = set(ids)
    kept = [t for t in tasks if t["task_id"] in allow]
    kept.sort(key=lambda t: order[t["task_id"]])
    missing = allow - {t["task_id"] for t in kept}
    if missing:
        raise ValueError(
            f"subset references {len(missing)} task_ids not in dataset "
            f"(e.g. {next(iter(missing))!r})"
        )
    return kept


# ---------- Scoring ----------

_GAIA_SCORER = None
_GAIA_SCORER_LOCK = threading.Lock()


def _get_gaia_scorer():
    """Lazily build the shared GAIA scorer (normalized exact-match + LLM judge).

    Judge model defaults to ``gpt-5-mini-2025-08-07`` (override via
    ``OPENJARVIS_GAIA_JUDGE_MODEL``); the judge backend is the ``cloud``
    engine, so ``OPENJARVIS_CONFIG`` needs a ``[engine.cloud]`` section.
    """
    global _GAIA_SCORER
    if _GAIA_SCORER is None:
        with _GAIA_SCORER_LOCK:
            if _GAIA_SCORER is None:
                from openjarvis.evals.backends.jarvis_direct import (
                    JarvisDirectBackend,
                )
                from openjarvis.evals.scorers.gaia_exact import GAIAScorer

                judge_model = os.environ.get(
                    "OPENJARVIS_GAIA_JUDGE_MODEL", "gpt-5-mini-2025-08-07"
                )
                try:
                    backend = JarvisDirectBackend(engine_key="cloud")
                except Exception:  # noqa: BLE001
                    backend = None
                _GAIA_SCORER = GAIAScorer(backend, judge_model)
    return _GAIA_SCORER


def _score_gaia(task: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """GAIA scorer — normalized exact-match with an LLM-judge fallback.

    Uses the shared OpenJarvis :class:`GAIAScorer`. The previous version
    only credited answers that emitted a literal ``FINAL ANSWER:`` line and
    string-matched it; a verbose answer that stated the right answer in
    prose silently scored 0. Opus emits the marker ~92% of the time but
    GPT-5-mini / Haiku almost never do, so their GAIA cells were badly
    undercounted. The judge recovers the answer from prose instead.
    """
    from openjarvis.evals.core.types import EvalRecord

    ref = (task.get("reference") or "").strip()
    if not ref:
        return {"success": False, "score": 0.0, "details": {"reason": "no_reference"}}

    record = EvalRecord(
        record_id=str(task.get("task_id") or ""),
        problem=str(task.get("question") or ""),
        reference=ref,
        category="agentic",
        metadata=dict(task.get("metadata") or {}),
    )
    is_correct, details = _get_gaia_scorer().score(record, answer or "")
    details = dict(details or {})
    details.setdefault("reference", ref)
    return {
        "success": bool(is_correct),
        "score": 1.0 if is_correct else 0.0,
        "details": details,
    }


def _score_swebench(
    task: Dict[str, Any],
    answer: str,
    cell_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Modal-backed SWE-bench Verified harness scorer.

    ``cell_name`` is passed through to :class:`SWEBenchHarnessScorer` so the
    underlying ``run_id`` is unique per (cell, instance). Without it,
    concurrent hybrid cells scoring the same task collide on the shared
    swebench harness cache and the second cell silently scores 0 with
    ``reason: no_report`` (or reads the first cell's verdict).
    """
    from openjarvis.evals.core.types import EvalRecord
    from openjarvis.evals.scorers.swebench_harness import (
        SWEBenchHarnessScorer,
        extract_patch,
    )

    patch = extract_patch(answer)
    if patch is None:
        return {
            "success": False,
            "score": 0.0,
            "details": {"reason": "no_patch_extracted"},
        }

    record = EvalRecord(
        record_id=task["task_id"],
        problem=task.get("problem_statement", ""),
        reference="",
        category="agentic",
        metadata={"instance_id": task["task_id"]},
    )
    scorer = SWEBenchHarnessScorer(
        timeout_s=int(os.environ.get("SWEBENCH_TIMEOUT_S", "1800")),
        cell_name=cell_name,
    )
    is_correct, details = scorer.score(record, answer)
    return {
        "success": bool(is_correct),
        "score": 1.0 if is_correct else 0.0,
        "details": details,
    }


def score(
    bench: str,
    task: Dict[str, Any],
    answer: str,
    cell_name: Optional[str] = None,
) -> Dict[str, Any]:
    if bench == "gaia":
        return _score_gaia(task, answer)
    if bench in ("swebench-verified", "swebench_verified", "swebench"):
        return _score_swebench(task, answer, cell_name=cell_name)
    raise ValueError(f"unknown bench: {bench!r}")


# ---------- Cell run ----------


def _cell_dir(cell_name: str, root: Path) -> Path:
    d = root / cell_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "logs").mkdir(exist_ok=True)
    return d


@contextmanager
def _cell_lock(out_dir: Path, cell_name: str):
    """Exclusive flock on ``<cell>/.lock`` to prevent concurrent runner stomps."""
    lock_path = out_dir / ".lock"
    f = lock_path.open("a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.seek(0)
        prev = (f.read() or "?").strip() or "?"
        f.close()
        raise SystemExit(
            f"[lock] another runner is already running cell {cell_name!r} "
            f"(holder pid: {prev}). refusing to start a second instance."
        )
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    try:
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        f.close()
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _build_agent(cell: Dict[str, Any]):
    """Construct the registered agent for this cell."""
    import openjarvis.agents  # noqa: F401 — populate registry
    from openjarvis.core.registry import AgentRegistry

    method = cell["method"]
    if not AgentRegistry.contains(method):
        raise ValueError(
            f"agent {method!r} not registered. Available: "
            f"{', '.join(sorted(AgentRegistry.keys()))}"
        )
    agent_cls = AgentRegistry.get(method)
    local = cell.get("local") or {}
    cloud = cell.get("cloud") or {}
    method_cfg = dict(cell.get("method_cfg") or {})

    return agent_cls(
        engine=None,  # raw SDK calls — engine unused
        model=cloud.get("model", ""),
        local_model=local.get("model"),
        local_endpoint=local.get("endpoint"),
        cloud_endpoint=(cloud.get("endpoint") or "anthropic").lower(),
        cfg=method_cfg,
    )


def _error_row(task: Dict[str, Any], t0: float, error: str) -> Dict[str, Any]:
    """Build a hybrid-shape error row (kept null-shaped like the catch path
    in :func:`_run_one` so the resume logic re-runs it)."""
    return {
        "task_id": task["task_id"],
        "answer": "",
        "tokens_local": 0,
        "tokens_cloud": 0,
        "cost_usd": 0.0,
        "latency_s": time.time() - t0,
        "web_search_uses": 0,
        "tool_calls": 0,
        "n_cloud_calls": 0,
        "n_local_calls": 0,
        "traces": {},
        "error": error,
    }


def _run_one_inner(
    agent, bench: str, task: Dict[str, Any], log_dir: str
) -> Dict[str, Any]:
    """Run the agent on one task. Returns a hybrid-shape row."""
    prompt = _format_prompt(task)
    ctx = AgentContext(
        metadata={
            "task": task,
            "task_id": task["task_id"],
            "log_dir": log_dir,
        }
    )
    t0 = time.time()
    try:
        result: AgentResult = agent.run(prompt, ctx)
        meta = dict(result.metadata or {})
        out = {
            "task_id": task["task_id"],
            "answer": result.content or "",
            "tokens_local": int(meta.get("tokens_local", 0)),
            "tokens_cloud": int(meta.get("tokens_cloud", 0)),
            "cost_usd": float(meta.get("cost_usd", 0.0)),
            "latency_s": float(meta.get("latency_s", time.time() - t0)),
            "web_search_uses": int(meta.get("web_search_uses", 0)),
            "tool_calls": int(meta.get("tool_calls", 0)),
            "n_cloud_calls": int(meta.get("n_cloud_calls", 0)),
            "n_local_calls": int(meta.get("n_local_calls", 0)),
            "traces": meta.get("traces", {}),
        }
        if "soft_error" in meta:
            out["soft_error"] = meta["soft_error"]
        return {**out, "error": None}
    except Exception as e:
        return _error_row(
            task, t0, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        )


def _run_one(
    agent,
    bench: str,
    task: Dict[str, Any],
    log_dir: str,
    *,
    task_timeout_s: float = DEFAULT_TASK_TIMEOUT_S,
) -> Dict[str, Any]:
    """Run one task under a hard wall-clock cap.

    ``_run_one_inner`` runs on a dedicated **daemon** thread; if it doesn't
    finish within ``task_timeout_s`` we give up on it and record a
    ``TaskTimeout`` error row. The worker thread is then *abandoned* — a
    truly wedged task (hung socket read with no enforced timeout, a Modal
    harness subprocess deadlocked draining pipes) cannot be killed
    cooperatively in CPython, so leaking the thread is the only safe
    option. It's a daemon thread, so it never blocks process exit, and the
    leak is bounded (one per timed-out task) — far cheaper than letting the
    whole cell freeze on the runner's ``as_completed`` join. The error row
    makes the resume logic re-run the task on the next invocation.

    ``task_timeout_s <= 0`` disables the cap (runs inline, legacy behavior).
    """
    t0 = time.time()
    if task_timeout_s <= 0:
        return _run_one_inner(agent, bench, task, log_dir)

    box: Dict[str, Any] = {}

    def _target() -> None:
        try:
            box["row"] = _run_one_inner(agent, bench, task, log_dir)
        except BaseException as e:  # noqa: BLE001 — never let the worker die silently
            box["row"] = _error_row(
                task, t0, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )

    worker = threading.Thread(
        target=_target,
        name=f"hybrid-task-{task['task_id']}",
        daemon=True,
    )
    worker.start()
    worker.join(timeout=task_timeout_s)
    if worker.is_alive():
        print(
            f"[timeout] task={task['task_id']} exceeded "
            f"{task_timeout_s / 60:.1f}m — abandoning worker, recording error row",
            flush=True,
        )
        return _error_row(
            task,
            t0,
            f"TaskTimeout: task exceeded the {task_timeout_s:.0f}s hybrid "
            "per-task wall-clock cap (likely a hung network or Modal-harness "
            "call); worker thread abandoned, task left for resume.",
        )
    return box.get("row") or _error_row(
        task, t0, "TaskError: worker thread exited without producing a row."
    )


def _heartbeat(done: int, total: int, row: Dict[str, Any], t_start: float) -> None:
    elapsed = time.time() - t_start
    eta = (total - done) * (elapsed / max(done, 1))
    ok = "OK" if not row.get("error") else "ERR"
    s = row.get("score") or {}
    sc = s.get("score")
    sc_str = f"{sc:.2f}" if isinstance(sc, (int, float)) else "—"
    print(
        f"[{done}/{total}] {ok} task={row['task_id']} score={sc_str} "
        f"local={row['tokens_local']} cloud={row['tokens_cloud']} "
        f"${row['cost_usd']:.3f} {row['latency_s']:.1f}s eta={eta / 60:.1f}m",
        flush=True,
    )


def _write_summary(
    out_dir: Path,
    cell_name: str,
    cell: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    t_start: float,
    n_processed: int = -1,
    energy_j_session: float = 0.0,
) -> None:
    results_path = out_dir / "results.jsonl"
    rows = [
        json.loads(line)
        for line in results_path.read_text().splitlines()
        if line.strip()
    ]
    n_done = len(rows)
    n_err = sum(1 for r in rows if r.get("error"))
    successes = [r for r in rows if r.get("score") and r["score"].get("success")]
    acc = (len(successes) / n_done) if n_done else 0.0
    total_cost = sum(r.get("cost_usd", 0.0) for r in rows)
    total_local = sum(r.get("tokens_local", 0) for r in rows)
    total_cloud = sum(r.get("tokens_cloud", 0) for r in rows)
    total_web_searches = sum(int(r.get("web_search_uses", 0) or 0) for r in rows)
    total_tool_calls = sum(int(r.get("tool_calls", 0) or 0) for r in rows)
    total_cloud_calls = sum(int(r.get("n_cloud_calls", 0) or 0) for r in rows)
    total_local_calls = sum(int(r.get("n_local_calls", 0) or 0) for r in rows)
    elapsed = time.time() - t_start

    # Preserve prior wall_time_s on no-op resume so we don't clobber the
    # original run's runtime. A resume that did zero work (everything was
    # already cached in results.jsonl) records ~seconds of elapsed time;
    # writing that as wall_time_s makes the cell look 20× faster than it
    # really was. If we did process anything this session, accumulate so
    # partial-resumes still report total wall time honestly.
    summary_path = out_dir / "summary.json"
    prior_wall = 0.0
    prior_energy = 0.0
    if summary_path.exists():
        try:
            prior = json.loads(summary_path.read_text())
            prior_wall = float(prior.get("wall_time_s", 0.0) or 0.0)
            prior_energy = float(prior.get("energy_j_total", 0.0) or 0.0)
        except Exception:
            prior_wall = 0.0
            prior_energy = 0.0
    if n_processed == 0 and prior_wall > 0:
        wall = prior_wall
        # No work done this session → keep prior energy total (don't add a
        # spurious idle-load reading from a resume that processed nothing).
        energy_j = prior_energy
    else:
        wall = prior_wall + elapsed
        energy_j = prior_energy + float(energy_j_session or 0.0)

    summary = {
        "cell": cell_name,
        "method": cell["method"],
        "bench": cell["bench"],
        "n_target": cell["n"],
        "n_done": n_done,
        "n_err": n_err,
        "accuracy": acc,
        "tokens_local_total": total_local,
        "tokens_cloud_total": total_cloud,
        "web_search_uses_total": total_web_searches,
        "tool_calls_total": total_tool_calls,
        "n_cloud_calls_total": total_cloud_calls,
        "n_local_calls_total": total_local_calls,
        "cost_usd_total": total_cost,
        "wall_time_s": wall,
        # GPU energy integrated over the cell's wall-time across the GPUs
        # visible to the runner host. Cloud energy is **not** included —
        # see ``_energy.py``. Joules; sum of session + any prior resumes.
        # TODO: decide whether to add a cloud J/token estimate; for now 0
        # cloud contribution. (Patterson 2021 / Luccioni 2022 are options.)
        "energy_j_total": energy_j,
        "task_count": len(tasks),
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    print(
        f"[summary] {cell_name}: n={n_done}/{cell['n']} err={n_err} "
        f"acc={acc:.3f} cost=${total_cost:.2f} time={wall / 60:.1f}m "
        f"energy={energy_j / 1000:.1f}kJ "
        f"(session +{elapsed / 60:.1f}m +{energy_j_session / 1000:.1f}kJ, "
        f"processed={n_processed})",
        flush=True,
    )


def run_cell(
    cell_name: str,
    cell: Dict[str, Any],
    *,
    do_score: bool = True,
    resume: bool = True,
    root: Optional[Path] = None,
) -> None:
    out_root = root or DEFAULT_RUNS_DIR
    out_dir = _cell_dir(cell_name, out_root)
    with _cell_lock(out_dir, cell_name):
        _run_cell_locked(
            cell_name,
            cell,
            out_dir,
            do_score=do_score,
            resume=resume,
        )


def _run_cell_locked(
    cell_name: str,
    cell: Dict[str, Any],
    out_dir: Path,
    *,
    do_score: bool,
    resume: bool,
) -> None:
    (out_dir / "config.json").write_text(
        json.dumps({"name": cell_name, **cell}, indent=2)
    )

    results_path = out_dir / "results.jsonl"
    done_ids: set = set()
    if resume and results_path.exists():
        # Keep only successful rows; drop errored rows so they retry.
        kept: List[str] = []
        for line in results_path.read_text().splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not row.get("error"):
                kept.append(line)
                done_ids.add(row["task_id"])
        results_path.write_text("\n".join(kept) + ("\n" if kept else ""))
        print(
            f"[resume] {len(done_ids)} tasks already done (errored rows dropped)",
            flush=True,
        )

    subset_path = cell.get("subset")
    if subset_path:
        subset = _load_subset_file(subset_path)
        # Load the full bench (n=None) so we can pick the exact subset IDs.
        # The dataset providers are cached, so this isn't a re-fetch.
        all_tasks = load_tasks(cell["bench"], n=None)
        tasks = _apply_subset(all_tasks, subset, cell)
        print(
            f"[load] {cell['bench']} subset={Path(subset_path).name} "
            f"→ {len(tasks)} tasks",
            flush=True,
        )
    else:
        tasks = load_tasks(cell["bench"], n=cell["n"])
        print(f"[load] {cell['bench']} → {len(tasks)} tasks", flush=True)

    pending = [t for t in tasks if t["task_id"] not in done_ids]
    concurrency = max(1, int(cell.get("concurrency", 1)))
    if concurrency > 1:
        print(f"[concurrency] {concurrency} workers", flush=True)

    # Hard per-task wall-clock cap. A cell may override it via the registry
    # (``method_cfg.task_timeout_s``); otherwise the process-wide default
    # (env ``OPENJARVIS_HYBRID_TASK_TIMEOUT_S``, 1800s) applies. 0 disables.
    mcfg = cell.get("method_cfg") or {}
    task_timeout_s = float(mcfg.get("task_timeout_s", DEFAULT_TASK_TIMEOUT_S))
    if task_timeout_s > 0:
        print(f"[task-timeout] {task_timeout_s / 60:.1f}m per task", flush=True)

    agent = _build_agent(cell)

    t_start = time.time()
    write_lock = threading.Lock()
    completed = [0]
    written_ok_ids: set = set()
    log_dir = str(out_dir / "logs")

    def _process(task: Dict[str, Any]) -> None:
        row = _run_one(
            agent,
            cell["bench"],
            task,
            log_dir,
            task_timeout_s=task_timeout_s,
        )
        scored: Optional[Dict[str, Any]] = None
        if do_score and row.get("error") is None:
            try:
                scored = score(
                    cell["bench"],
                    task,
                    row["answer"],
                    cell_name=cell_name,
                )
            except Exception as e:
                scored = {
                    "success": False,
                    "score": 0.0,
                    "details": {"score_error": str(e)},
                }
        full_row = {**row, "score": scored}
        with write_lock:
            # Idempotency guard: a Modal retry can re-run the same task within
            # one process. Skip appending once a non-error row exists for this
            # task_id so results.jsonl never carries duplicate rows.
            if full_row["task_id"] in written_ok_ids:
                return
            with results_path.open("a") as f:
                f.write(json.dumps(full_row) + "\n")
                f.flush()
            if full_row.get("error") is None:
                written_ok_ids.add(full_row["task_id"])
            completed[0] += 1
            _heartbeat(completed[0], len(tasks), full_row, t_start)

    # Hard watchdog. The per-task ``worker.join(timeout=task_timeout_s)`` in
    # ``_run_one`` is supposed to bound any single task, but in practice we've
    # seen the main loop wedge in ``futex_wait_queue`` despite the join
    # returning — likely a daemon thread holding a non-Python lock that the
    # GC / atexit handler trips on. Defense in depth: if no row hits
    # ``results.jsonl`` in ``watchdog_stale_s = 2 * task_timeout_s + 600``
    # seconds, ``os._exit(2)`` the whole process. The wrapper script's
    # resume logic will pick up unscored tasks on the next invocation, and
    # we don't burn another 30+ min on a wedge. Disabled when
    # ``task_timeout_s <= 0`` (matches the legacy in-process timeout knob).
    watchdog_stale_s = (2 * task_timeout_s + 600) if task_timeout_s > 0 else 0
    watchdog_stop = threading.Event()

    def _watchdog() -> None:
        baseline_mtime = (
            results_path.stat().st_mtime if results_path.exists() else time.time()
        )
        last_seen = baseline_mtime
        while not watchdog_stop.wait(60.0):
            try:
                cur = (
                    results_path.stat().st_mtime if results_path.exists() else last_seen
                )
            except Exception:
                cur = last_seen
            if cur > last_seen:
                last_seen = cur
                continue
            if time.time() - last_seen > watchdog_stale_s:
                print(
                    f"[watchdog] results.jsonl stale for "
                    f"{int(time.time() - last_seen)}s "
                    f"(threshold {int(watchdog_stale_s)}s) — hard-exit, "
                    f"resume on next invocation.",
                    flush=True,
                )
                os._exit(2)

    if watchdog_stale_s > 0:
        threading.Thread(
            target=_watchdog, name="hybrid-runner-watchdog", daemon=True
        ).start()

    # GPU energy sampler covers the same wall-clock window as ``wall_time_s``
    # so the two numbers can be divided into an effective Watts figure.
    # Sampler is best-effort: NVML failures degrade to ``energy_j_total=0``
    # without crashing the run (see ``_energy.py``).
    with EnergyCollector() as energy:
        if concurrency == 1:
            for task in pending:
                _process(task)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as ex:
                futures = [ex.submit(_process, t) for t in pending]
                for fut in as_completed(futures):
                    fut.result()

    watchdog_stop.set()

    _write_summary(
        out_dir,
        cell_name,
        cell,
        tasks,
        t_start,
        n_processed=len(pending),
        energy_j_session=energy.energy_j_total,
    )


# ---------- CLI ----------


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m openjarvis.agents.hybrid.runner",
        description="Run a hybrid paradigm experiment cell.",
    )
    p.add_argument("--cell", required=True, help="Cell name from the registry TOMLs.")
    p.add_argument(
        "--registry-dir",
        default=None,
        help="Override registry dir (defaults to package registry/).",
    )
    p.add_argument(
        "--root",
        default=None,
        help="Override experiments output root.",
    )
    p.add_argument("--no-score", action="store_true", help="Skip scoring.")
    p.add_argument(
        "--no-resume", action="store_true", help="Don't resume from results.jsonl."
    )
    args = p.parse_args(argv)

    reg_dir = Path(args.registry_dir) if args.registry_dir else None
    cells = load_registry(reg_dir)
    if not cells:
        print(
            f"[error] no cells found in {reg_dir or DEFAULT_REGISTRY_DIR}",
            file=sys.stderr,
        )
        return 2
    if args.cell not in cells:
        print(
            f"[error] unknown cell {args.cell!r}. Known: {', '.join(sorted(cells))}",
            file=sys.stderr,
        )
        return 2
    root = Path(args.root) if args.root else None
    run_cell(
        args.cell,
        cells[args.cell],
        do_score=not args.no_score,
        resume=not args.no_resume,
        root=root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_EXPERIMENTS_DIR",
    "DEFAULT_RUNS_DIR",
    "DEFAULT_REGISTRY_DIR",
    "load_registry",
    "load_tasks",
    "main",
    "run_cell",
    "score",
]
