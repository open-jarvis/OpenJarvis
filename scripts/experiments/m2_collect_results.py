#!/usr/bin/env python3
"""M2: Collect distilled eval results and produce comparison table.

Reads .summary.json files from results/neurips-2026/{distilled,baselines}/
and produces a before/after comparison against the Step 1 baseline numbers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Jon's Step 1 baselines — used when a local baseline result doesn't exist
STEP1_BASELINES = {
    "2b":  {"toolcall15": 33.3, "pinchbench": 69.6, "livecodebench": 5.6,  "taubench": 70.0, "taubench-telecom": 0.0,  "gaia": 0.0,  "liveresearch": 0.0,  "liveresearchbench": None},
    "9b":  {"toolcall15": 46.7, "pinchbench": 95.7, "livecodebench": 17.6, "taubench": 85.0, "taubench-telecom": 80.0, "gaia": 38.0, "liveresearch": 75.0, "liveresearchbench": None},
    "27b": {"toolcall15": 40.0, "pinchbench": 65.2, "livecodebench": 20.0, "taubench": 75.0, "taubench-telecom": 75.0, "gaia": 48.0, "liveresearch": 66.7, "liveresearchbench": None},
}

# Which benchmarks go through the agent layer (where distillation edits actually apply)
AGENT_BENCHMARKS = {"pinchbench", "gaia", "liveresearch"}

DISTILLED_ROOT = Path("results/neurips-2026/distilled")
BASELINE_ROOT = Path("results/neurips-2026/baselines")


def find_summary(root: Path, size: str, bench: str) -> Path | None:
    """Find the summary JSON for a model × benchmark run."""
    # Expected path: root/qwen-{size}/{bench}/{bench}_Qwen-Qwen3.5-{size}.summary.json
    candidates = list(root.glob(f"qwen-{size}/{bench}/*.summary.json"))
    return candidates[0] if candidates else None


def load_accuracy(summary_path: Path) -> float | None:
    """Extract overall accuracy from a summary.json file."""
    try:
        d = json.loads(summary_path.read_text())
        # The summary has various shapes; try a few
        for key in ["overall_accuracy", "accuracy", "overall_score"]:
            if key in d:
                return float(d[key]) * 100 if d[key] <= 1.0 else float(d[key])
        # Try nested
        if "results" in d:
            for r in d["results"]:
                if "accuracy" in r:
                    return float(r["accuracy"]) * 100 if r["accuracy"] <= 1.0 else float(r["accuracy"])
    except Exception as e:
        print(f"  error reading {summary_path}: {e}", file=sys.stderr)
    return None


def main() -> int:
    print("=" * 100)
    print("M2 Distilled vs Baseline Comparison")
    print("=" * 100)
    print()
    print(f"{'Model':8} {'Benchmark':20} {'Baseline':>10} {'Distilled':>10} {'Delta':>10} {'Agent?':>10}")
    print("-" * 100)

    benchmarks = [
        "toolcall15", "pinchbench", "livecodebench",
        "taubench", "taubench-telecom",
        "gaia", "liveresearch", "liveresearchbench",
    ]

    summary_rows = []
    for size in ["2b", "9b", "27b"]:
        for bench in benchmarks:
            # Baseline: prefer local file (if run this session), fall back to Step 1 numbers
            baseline_path = find_summary(BASELINE_ROOT, size, bench)
            if baseline_path:
                baseline = load_accuracy(baseline_path)
                base_source = "local"
            else:
                baseline = STEP1_BASELINES[size].get(bench)
                base_source = "step1"

            # Distilled: must be local from this session
            distilled_path = find_summary(DISTILLED_ROOT, size, bench)
            distilled = load_accuracy(distilled_path) if distilled_path else None

            # Format
            b_str = f"{baseline:.1f}%" if baseline is not None else "—"
            d_str = f"{distilled:.1f}%" if distilled is not None else "pending"
            if baseline is not None and distilled is not None:
                delta = distilled - baseline
                d_sign = "+" if delta >= 0 else ""
                delta_str = f"{d_sign}{delta:.1f}%"
            else:
                delta_str = "—"
            agent = "AGENT" if bench in AGENT_BENCHMARKS else "direct"

            print(f"qwen-{size:4} {bench:20} {b_str:>10} {d_str:>10} {delta_str:>10} {agent:>10}")
            summary_rows.append({
                "model": f"qwen-{size}",
                "benchmark": bench,
                "baseline": baseline,
                "distilled": distilled,
                "delta": distilled - baseline if (baseline is not None and distilled is not None) else None,
                "agent_benchmark": bench in AGENT_BENCHMARKS,
            })
        print()

    # Aggregate: agent vs direct benchmark deltas
    print("=" * 100)
    print("Aggregate deltas by benchmark type (paper finding)")
    print("=" * 100)
    agent_deltas = [r["delta"] for r in summary_rows if r["delta"] is not None and r["agent_benchmark"]]
    direct_deltas = [r["delta"] for r in summary_rows if r["delta"] is not None and not r["agent_benchmark"]]
    if agent_deltas:
        mean_agent = sum(agent_deltas) / len(agent_deltas)
        print(f"Agent benchmarks (PB, GAIA, DeepResearchBench): mean delta = {mean_agent:+.2f}% over {len(agent_deltas)} runs")
    if direct_deltas:
        mean_direct = sum(direct_deltas) / len(direct_deltas)
        print(f"Direct benchmarks (TC15, TauB, TBTel, LRB, LCB): mean delta = {mean_direct:+.2f}% over {len(direct_deltas)} runs")
    print()

    # Completion progress
    expected = 24
    distilled_count = sum(1 for r in summary_rows if r["distilled"] is not None)
    print(f"Distilled runs complete: {distilled_count}/{expected}")

    # Save JSON
    out = Path("results/neurips-2026/distillation-m2/m2_comparison.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary_rows, indent=2, default=str))
    print(f"Full data: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
