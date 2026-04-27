#!/usr/bin/env python3
"""Compare distilled vs baseline eval results across the matrix.

Reads ``*.summary.json`` files written by the eval runner (steps 1 and 6)
from both the baseline and distilled results trees, computes per-cell
deltas, splits agent vs direct benchmarks, and writes a JSON summary.

Usage:
    python 7_compare_results.py
    python 7_compare_results.py --baseline-results path/to/old/baselines
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

REPO_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEFAULT_MATRIX = HERE / "pipeline_matrix.toml"


def hf_to_summary_slug(hf_name: str) -> str:
    return hf_name.replace("/", "-")


def expected_summary_path(*, results_root: Path, app: dict, exp: dict) -> Path:
    bench_for_filename = exp.get("benchmark_name", exp["name"])
    model_slug = hf_to_summary_slug(app["hf_name"])
    return (
        results_root
        / app["slug"]
        / exp["name"]
        / f"{bench_for_filename}_{model_slug}.summary.json"
    )


def load_accuracy(summary_path: Path) -> float | None:
    """Pull a percentage-scale accuracy out of a summary.json."""
    if not summary_path.exists():
        return None
    try:
        d: dict[str, Any] = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    for key in ("overall_accuracy", "accuracy", "overall_score"):
        if key in d:
            v = float(d[key])
            return v * 100 if v <= 1.0 else v
    if "results" in d:
        for r in d["results"]:
            if "accuracy" in r:
                v = float(r["accuracy"])
                return v * 100 if v <= 1.0 else v
    return None


def fmt_pct(v: float | None) -> str:
    return f"{v:.1f}%" if v is not None else "—"


def fmt_delta(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument(
        "--baseline-results",
        type=Path,
        default=None,
        help="Override the baseline results dir (default: from matrix).",
    )
    p.add_argument(
        "--distilled-results",
        type=Path,
        default=None,
        help="Override the distilled results dir (default: from matrix).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON output path (default: <comparison_dir>/comparison.json).",
    )
    args = p.parse_args(argv)

    matrix = tomllib.loads(args.matrix.read_text())
    paths = matrix["paths"]
    baseline_root = args.baseline_results or (REPO_ROOT / paths["baseline_results_dir"])
    distilled_root = args.distilled_results or (
        REPO_ROOT / paths["distilled_results_dir"]
    )
    out_path = args.out or (REPO_ROOT / paths["comparison_dir"] / "comparison.json")

    apps = matrix["applications"]
    exps = matrix["experiments"]

    print("=" * 100)
    print("Distilled vs Baseline Comparison")
    print("=" * 100)
    print(f"  baseline_results : {baseline_root}")
    print(f"  distilled_results: {distilled_root}")
    print()
    header = f"{'app':10} {'experiment':22} {'baseline':>10} {'distilled':>10} {'delta':>10}  {'kind':<6}"
    print(header)
    print("-" * len(header))

    rows: list[dict] = []
    for app in apps:
        for exp in exps:
            b_path = expected_summary_path(results_root=baseline_root, app=app, exp=exp)
            d_path = expected_summary_path(
                results_root=distilled_root, app=app, exp=exp
            )
            baseline = load_accuracy(b_path)
            distilled = load_accuracy(d_path)
            delta = (
                (distilled - baseline)
                if (baseline is not None and distilled is not None)
                else None
            )
            kind = "agent" if exp.get("is_agent") else "direct"
            rows.append(
                {
                    "app": app["slug"],
                    "experiment": exp["name"],
                    "is_agent": bool(exp.get("is_agent")),
                    "is_control": bool(exp.get("is_control")),
                    "baseline": baseline,
                    "distilled": distilled,
                    "delta": delta,
                    "baseline_path": str(b_path),
                    "distilled_path": str(d_path),
                }
            )
            print(
                f"{app['slug']:10} {exp['name']:22} {fmt_pct(baseline):>10} "
                f"{fmt_pct(distilled):>10} {fmt_delta(delta):>10}  {kind:<6}"
            )
        print()

    # ── Aggregate by kind ────────────────────────────────────────────────────
    print("=" * 100)
    print("Aggregate deltas")
    print("=" * 100)
    for label, predicate in [
        (
            "agent (distilled effect expected)",
            lambda r: r["is_agent"] and not r["is_control"],
        ),
        ("direct controls", lambda r: not r["is_agent"] or r["is_control"]),
    ]:
        deltas = [r["delta"] for r in rows if r["delta"] is not None and predicate(r)]
        if deltas:
            mean = sum(deltas) / len(deltas)
            print(f"  {label:42}  mean Δ = {mean:+.2f}%  over {len(deltas)} runs")
        else:
            print(f"  {label:42}  (no completed cells)")

    # ── Completion ───────────────────────────────────────────────────────────
    n_total = len(rows)
    n_distilled = sum(1 for r in rows if r["distilled"] is not None)
    n_baseline = sum(1 for r in rows if r["baseline"] is not None)
    print()
    print(f"  baseline runs complete : {n_baseline}/{n_total}")
    print(f"  distilled runs complete: {n_distilled}/{n_total}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "baseline_results_dir": str(baseline_root),
                "distilled_results_dir": str(distilled_root),
                "rows": rows,
            },
            indent=2,
            default=str,
        )
    )
    print()
    print(f"Full data → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
