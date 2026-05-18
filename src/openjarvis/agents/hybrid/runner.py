"""CLI runner for hybrid paradigm experiments.

::

    python -m openjarvis.agents.hybrid.runner --cell minions-gaia-qwen27b-opus-3

Reads a cell definition from ``registry/<method>.toml`` (bundled with this
package or pointed at by ``OPENJARVIS_HYBRID_REGISTRY_DIR``), constructs
the registered agent, loads bench tasks via OpenJarvis's existing dataset
providers, runs every task, scores it, and writes
``<EXPERIMENTS_DIR>/<cell>/results.jsonl`` + ``summary.json``.

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
from openjarvis.agents.hybrid._prompts import format_prompt as _format_prompt

PACKAGE_DIR = Path(__file__).parent
DEFAULT_REGISTRY_DIR = PACKAGE_DIR / "registry"
DEFAULT_EXPERIMENTS_DIR = Path(
    os.environ.get(
        "OPENJARVIS_HYBRID_EXPERIMENTS_DIR",
        str(Path.home() / ".openjarvis-hybrid" / "experiments"),
    )
)


# ---------- Registry ----------

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
        # the GAIA-specific fields including any reference answer.
        out.append({
            "task_id": rec.record_id,
            "question": rec.metadata.get("question", rec.problem),
            "reference": rec.reference,
            "metadata": dict(rec.metadata),
        })
    return out


def _load_swebench_tasks(n: Optional[int]) -> List[Dict[str, Any]]:
    """SWE-bench-Verified test. Each task carries patch-evaluation fields."""
    from openjarvis.evals.datasets.swebench import SWEBenchDataset

    ds = SWEBenchDataset()
    ds.load(max_samples=n)
    out: List[Dict[str, Any]] = []
    for rec in ds.iter_records():
        md = rec.metadata or {}
        out.append({
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
        })
    return out


def load_tasks(bench: str, n: Optional[int]) -> List[Dict[str, Any]]:
    if bench == "gaia":
        return _load_gaia_tasks(n)
    if bench in ("swebench-verified", "swebench_verified", "swebench"):
        return _load_swebench_tasks(n)
    raise ValueError(f"unknown bench: {bench!r}")


# ---------- Scoring ----------

def _score_gaia(task: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """Exact-match-with-format-normalization GAIA scorer.

    Lightweight version: extracts the final-answer line and string-compares
    against the reference. Use the OpenJarvis gaia_exact scorer for the
    judge-tiebreaker path.
    """
    import re

    ref = (task.get("reference") or "").strip()
    if not ref:
        return {"success": False, "score": 0.0, "details": {"reason": "no_reference"}}
    m = re.search(
        r"FINAL\s*ANSWER\s*:\s*(.+?)\s*$",
        answer,
        re.IGNORECASE | re.MULTILINE,
    )
    pred = (m.group(1).strip() if m else answer.strip()).rstrip(".").strip()
    success = pred.lower() == ref.lower()
    return {
        "success": success,
        "score": 1.0 if success else 0.0,
        "details": {"prediction": pred, "reference": ref},
    }


def _score_swebench(task: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """Modal-backed SWE-bench Verified harness scorer."""
    from openjarvis.evals.core.types import EvalRecord
    from openjarvis.evals.scorers.swebench_harness import (
        SWEBenchHarnessScorer,
        extract_patch,
    )

    patch = extract_patch(answer)
    if patch is None:
        return {"success": False, "score": 0.0, "details": {"reason": "no_patch_extracted"}}

    record = EvalRecord(
        record_id=task["task_id"],
        problem=task.get("problem_statement", ""),
        reference="",
        category="agentic",
        metadata={"instance_id": task["task_id"]},
    )
    scorer = SWEBenchHarnessScorer(timeout_s=int(os.environ.get("SWEBENCH_TIMEOUT_S", "1800")))
    is_correct, details = scorer.score(record, answer)
    return {
        "success": bool(is_correct),
        "score": 1.0 if is_correct else 0.0,
        "details": details,
    }


def score(bench: str, task: Dict[str, Any], answer: str) -> Dict[str, Any]:
    if bench == "gaia":
        return _score_gaia(task, answer)
    if bench in ("swebench-verified", "swebench_verified", "swebench"):
        return _score_swebench(task, answer)
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


def _run_one(agent, bench: str, task: Dict[str, Any], log_dir: str) -> Dict[str, Any]:
    """Run the agent on one task. Returns a hybrid-shape row."""
    prompt = _format_prompt(task)
    ctx = AgentContext(metadata={
        "task": task,
        "task_id": task["task_id"],
        "log_dir": log_dir,
    })
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
            "traces": meta.get("traces", {}),
        }
        if "soft_error" in meta:
            out["soft_error"] = meta["soft_error"]
        return {**out, "error": None}
    except Exception as e:
        return {
            "task_id": task["task_id"],
            "answer": "",
            "tokens_local": 0, "tokens_cloud": 0,
            "cost_usd": 0.0, "latency_s": time.time() - t0,
            "traces": {},
            "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        }


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
        f"${row['cost_usd']:.3f} {row['latency_s']:.1f}s eta={eta/60:.1f}m",
        flush=True,
    )


def _write_summary(
    out_dir: Path,
    cell_name: str,
    cell: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    t_start: float,
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
    elapsed = time.time() - t_start

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
        "cost_usd_total": total_cost,
        "wall_time_s": elapsed,
        "task_count": len(tasks),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(
        f"[summary] {cell_name}: n={n_done}/{cell['n']} err={n_err} "
        f"acc={acc:.3f} cost=${total_cost:.2f} time={elapsed/60:.1f}m",
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
    out_root = root or DEFAULT_EXPERIMENTS_DIR
    out_dir = _cell_dir(cell_name, out_root)
    with _cell_lock(out_dir, cell_name):
        _run_cell_locked(
            cell_name, cell, out_dir,
            do_score=do_score, resume=resume,
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

    tasks = load_tasks(cell["bench"], n=cell["n"])
    print(f"[load] {cell['bench']} → {len(tasks)} tasks", flush=True)

    pending = [t for t in tasks if t["task_id"] not in done_ids]
    concurrency = max(1, int(cell.get("concurrency", 1)))
    if concurrency > 1:
        print(f"[concurrency] {concurrency} workers", flush=True)

    agent = _build_agent(cell)

    t_start = time.time()
    write_lock = threading.Lock()
    completed = [0]
    log_dir = str(out_dir / "logs")

    def _process(task: Dict[str, Any]) -> None:
        row = _run_one(agent, cell["bench"], task, log_dir)
        scored: Optional[Dict[str, Any]] = None
        if do_score and row.get("error") is None:
            try:
                scored = score(cell["bench"], task, row["answer"])
            except Exception as e:
                scored = {
                    "success": False, "score": 0.0,
                    "details": {"score_error": str(e)},
                }
        full_row = {**row, "score": scored}
        with write_lock, results_path.open("a") as f:
            f.write(json.dumps(full_row) + "\n")
            f.flush()
            completed[0] += 1
            _heartbeat(completed[0], len(tasks), full_row, t_start)

    if concurrency == 1:
        for task in pending:
            _process(task)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = [ex.submit(_process, t) for t in pending]
            for fut in as_completed(futures):
                fut.result()

    _write_summary(out_dir, cell_name, cell, tasks, t_start)


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
    p.add_argument("--no-resume", action="store_true", help="Don't resume from results.jsonl.")
    args = p.parse_args(argv)

    reg_dir = Path(args.registry_dir) if args.registry_dir else None
    cells = load_registry(reg_dir)
    if not cells:
        print(f"[error] no cells found in {reg_dir or DEFAULT_REGISTRY_DIR}", file=sys.stderr)
        return 2
    if args.cell not in cells:
        print(
            f"[error] unknown cell {args.cell!r}. Known: {', '.join(sorted(cells))}",
            file=sys.stderr,
        )
        return 2
    root = Path(args.root) if args.root else None
    run_cell(
        args.cell, cells[args.cell],
        do_score=not args.no_score,
        resume=not args.no_resume,
        root=root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_EXPERIMENTS_DIR",
    "DEFAULT_REGISTRY_DIR",
    "load_registry",
    "load_tasks",
    "main",
    "run_cell",
    "score",
]
