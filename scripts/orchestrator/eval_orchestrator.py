#!/usr/bin/env python
"""Run the ToolOrchestra orchestrator over N-sample subsets of several
benchmarks and score them with the existing eval infra.

Reuses, verbatim:
  * ``openjarvis.evals.cli._build_dataset`` / ``_build_scorer`` /
    ``_build_judge_backend`` (loaders + scorers + judge wiring),
  * ``openjarvis.evals.core.runner.EvalRunner`` (parallel run + scoring),
  * ``openjarvis.evals.core.types.RunConfig`` (run config),

and plugs in our orchestrator as the "model" via
``openjarvis.learning.intelligence.orchestrator.eval_backend.OrchestratorBackend``.

For each benchmark it runs ``EvalRunner(config, dataset, backend, scorer).run()``,
collects accuracy / cost / latency, writes a combined ``summary.json``, and
prints a table.

NOTE on the judge: the OpenAI key is dead, so the default judge model is a
Gemini model (``gemini-2.5-flash``). The judge backend is still built via the
``cloud`` engine (``_build_judge_backend``) — the model string selects the
provider/route. Override with ``--judge-model`` / ``--judge-engine``.

Example
-------
    .venv/bin/python scripts/orchestrator/eval_orchestrator.py \\
        --benchmarks gaia,mmlu_pro --n 100 \\
        --orchestrator-endpoint http://localhost:8001/v1 \\
        --orchestrator-model qwen3-8b \\
        --output-dir ~/.openjarvis/experiments/hybrid/runs/orch-eval
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Friendly aliases (underscored / shorthand) -> the EXACT registry keys used by
# openjarvis.evals.cli.BENCHMARKS / _build_dataset / _build_scorer.
BENCHMARK_ALIASES: Dict[str, str] = {
    "terminalbench_v2_1": "terminalbench-v2.1",
    "terminalbench-v2_1": "terminalbench-v2.1",
    "terminalbench_v21": "terminalbench-v2.1",
    "terminalbench-v2.1": "terminalbench-v2.1",
    "mmlu_pro": "mmlu-pro",
    "mmlu-pro": "mmlu-pro",
    "gaia": "gaia",
    "taubench": "taubench",
    "supergpqa": "supergpqa",
}

DEFAULT_BENCHMARKS = "gaia,terminalbench_v2_1,taubench,mmlu_pro,supergpqa"


def _normalize_benchmark(name: str) -> str:
    key = name.strip()
    return BENCHMARK_ALIASES.get(key, BENCHMARK_ALIASES.get(key.lower(), key))


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the orchestrator over benchmark subsets and score them.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--benchmarks",
        default=DEFAULT_BENCHMARKS,
        help="Comma-separated benchmark names (aliases normalized to registry keys).",
    )
    p.add_argument("--n", type=int, default=100, help="Samples per benchmark.")
    p.add_argument("--seed", type=int, default=42, help="Subset seed.")
    p.add_argument(
        "--orchestrator-endpoint",
        default="http://localhost:8001/v1",
        help="OpenAI-compatible base URL for the served orchestrator.",
    )
    p.add_argument(
        "--orchestrator-model",
        default="qwen3-8b",
        help="Served orchestrator model id.",
    )
    p.add_argument(
        "--orchestrator-api-key",
        default="EMPTY",
        help="API key for the orchestrator endpoint (EMPTY for local vLLM).",
    )
    p.add_argument(
        "--local-endpoint",
        action="append",
        default=[],
        metavar="MODEL_ID=URL",
        help=(
            "Wire a local OSS tool: map a catalog model id to its vLLM base "
            "URL, e.g. 'Qwen/Qwen3.5-9B=http://localhost:8003/v1'. Repeatable."
        ),
    )
    p.add_argument(
        "--max-turns",
        type=int,
        default=8,
        help="Max orchestrator turns per sample.",
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=1.0,
        help="Orchestrator sampling temperature.",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Parallel samples per benchmark.",
    )
    p.add_argument(
        "--output-dir",
        default="results/orchestrator-eval",
        help="Directory for per-benchmark JSONL + combined summary.json.",
    )
    # NOTE: OpenAI key is dead — default the judge to a Gemini model.
    p.add_argument(
        "--judge-model",
        default="gemini-2.5-flash",
        help="LLM-judge model (default Gemini — OpenAI key is dead).",
    )
    p.add_argument(
        "--judge-engine",
        default="cloud",
        help="Engine key for the judge backend.",
    )
    return p.parse_args(argv)


def _run_one(
    benchmark: str,
    *,
    n: int,
    seed: int,
    backend,
    judge_model: str,
    judge_engine: str,
    max_workers: int,
    orchestrator_model: str,
    output_dir: Path,
) -> Dict[str, Any]:
    """Run + score one benchmark, returning a row dict (or an error row)."""
    # Imports here so --help works without importing the (heavy) eval stack.
    from openjarvis.evals.cli import (
        _build_dataset,
        _build_judge_backend,
        _build_scorer,
    )
    from openjarvis.evals.core.runner import EvalRunner
    from openjarvis.evals.core.types import RunConfig

    output_path = output_dir / f"{benchmark.replace('.', '_')}_orchestrator.jsonl"

    dataset = _build_dataset(benchmark)
    # The runner reloads internally; we also load here per spec so callers can
    # inspect/size the subset up front. load() is idempotent for these sets.
    dataset.load(max_samples=n, seed=seed)

    judge_backend = _build_judge_backend(judge_model, engine_key=judge_engine)
    scorer = _build_scorer(benchmark, judge_backend, judge_model)

    config = RunConfig(
        benchmark=benchmark,
        backend="orchestrator",
        model=orchestrator_model,
        max_samples=n,
        max_workers=max_workers,
        seed=seed,
        judge_model=judge_model,
        judge_engine=judge_engine,
        output_path=str(output_path),
    )

    runner = EvalRunner(config, dataset, backend, scorer)
    started = time.time()
    try:
        summary = runner.run()
    finally:
        if judge_backend is not None:
            judge_backend.close()
    elapsed = time.time() - started

    return {
        "benchmark": benchmark,
        "accuracy": summary.accuracy,
        "scored_samples": summary.scored_samples,
        "correct": summary.correct,
        "errors": summary.errors,
        "total_samples": summary.total_samples,
        "mean_latency_seconds": summary.mean_latency_seconds,
        "total_cost_usd": summary.total_cost_usd,
        "mean_continuous_score": summary.mean_continuous_score,
        "wall_seconds": round(elapsed, 2),
        "output_path": str(output_path),
    }


def _print_table(rows: List[Dict[str, Any]]) -> None:
    cols = [
        ("benchmark", 22, "{}"),
        ("accuracy", 9, "{:.4f}"),
        ("correct", 8, "{}"),
        ("scored", 7, "{}"),
        ("errors", 7, "{}"),
        ("cost($)", 10, "{:.4f}"),
        ("lat(s)", 9, "{:.2f}"),
        ("wall(s)", 9, "{:.1f}"),
    ]
    header = "  ".join(f"{name:<{w}}" for name, w, _ in cols)
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        if r.get("error"):
            print(f"{r['benchmark']:<22}  ERROR: {r['error']}")
            continue
        vals = {
            "benchmark": r["benchmark"],
            "accuracy": r["accuracy"],
            "correct": r["correct"],
            "scored": r["scored_samples"],
            "errors": r["errors"],
            "cost($)": r["total_cost_usd"],
            "lat(s)": r["mean_latency_seconds"],
            "wall(s)": r["wall_seconds"],
        }
        cells = []
        for name, w, fmt in cols:
            v = vals[name]
            try:
                s = fmt.format(v)
            except (ValueError, TypeError):
                s = str(v)
            cells.append(f"{s:<{w}}")
        print("  ".join(cells))


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    benchmarks = [
        _normalize_benchmark(b) for b in args.benchmarks.split(",") if b.strip()
    ]
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build the orchestrator backend once (stateless across benchmarks).
    from openjarvis.learning.intelligence.orchestrator.eval_backend import (
        OrchestratorBackend,
    )

    local_endpoints: Dict[str, str] = {}
    for pair in args.local_endpoint:
        if "=" not in pair:
            raise SystemExit(
                f"--local-endpoint expects MODEL_ID=URL, got: {pair!r}"
            )
        model_id, url = pair.split("=", 1)
        local_endpoints[model_id.strip()] = url.strip()

    backend = OrchestratorBackend(
        orchestrator_endpoint=args.orchestrator_endpoint,
        orchestrator_model=args.orchestrator_model,
        api_key=args.orchestrator_api_key,
        local_endpoints=local_endpoints,
        max_turns=args.max_turns,
        temperature=args.temperature,
    )

    rows: List[Dict[str, Any]] = []
    try:
        for benchmark in benchmarks:
            print(f"\n=== {benchmark} (n={args.n}, seed={args.seed}) ===")
            try:
                row = _run_one(
                    benchmark,
                    n=args.n,
                    seed=args.seed,
                    backend=backend,
                    judge_model=args.judge_model,
                    judge_engine=args.judge_engine,
                    max_workers=args.max_workers,
                    orchestrator_model=args.orchestrator_model,
                    output_dir=output_dir,
                )
                print(
                    f"  accuracy={row['accuracy']:.4f} "
                    f"({row['correct']}/{row['scored_samples']}) "
                    f"errors={row['errors']} cost=${row['total_cost_usd']:.4f}"
                )
            except Exception as exc:  # noqa: BLE001 - one bad bench shouldn't kill all
                print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
                row = {"benchmark": benchmark, "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
    finally:
        backend.close()

    combined = {
        "orchestrator_model": args.orchestrator_model,
        "orchestrator_endpoint": args.orchestrator_endpoint,
        "judge_model": args.judge_model,
        "judge_engine": args.judge_engine,
        "n": args.n,
        "seed": args.seed,
        "max_turns": args.max_turns,
        "benchmarks": rows,
    }
    summary_path = output_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(combined, f, indent=2, default=str)

    _print_table(rows)
    print(f"\nCombined summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
