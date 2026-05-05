"""LaTeX table generator for the framework-comparison harness.

Reads `summary.json` files produced by EvalRunner, builds a long-format
polars DataFrame, then renders 7 tables (T1..T7) as both `tabular`
fragments (paste-into-paper) and `\\documentclass{standalone}` previews
(latexmk-renderable).
"""

from __future__ import annotations

import glob
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click

try:
    import polars as pl
except ImportError as _polars_err:  # pragma: no cover
    raise ImportError(
        "polars is required for the framework-comparison table generator. "
        "Install with: uv sync --extra framework-comparison"
    ) from _polars_err

from pydantic import BaseModel, ValidationError

LOGGER = logging.getLogger(__name__)


class TableGenError(Exception):
    """Base for table-generation problems."""


class MixedCommitError(TableGenError):
    """Raised when one (framework, model, benchmark) cell has multiple commits."""


class _MetricStats(BaseModel):
    mean: float
    std: float
    n: int


class _SummarySchema(BaseModel):
    framework: str
    framework_commit: str
    model: str
    benchmark: str
    n_tasks: int
    metrics: Dict[str, _MetricStats]


@dataclass(slots=True)
class ResultsFrame:
    """Long-format DataFrame of all loaded summary.json results."""

    df: pl.DataFrame
    unloadable_count: int = 0


def load_results(glob_pattern: str) -> ResultsFrame:
    """Glob summary.json files, validate, return long-format ResultsFrame."""
    paths = glob.glob(glob_pattern, recursive=True)
    rows: List[Dict[str, object]] = []
    unloadable = 0

    for p in paths:
        try:
            raw = json.loads(Path(p).read_text())
            schema = _SummarySchema.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as e:
            LOGGER.warning("skipping unloadable summary at %s: %s", p, e)
            unloadable += 1
            continue
        for metric_name, stats in schema.metrics.items():
            rows.append(
                {
                    "framework": schema.framework,
                    "framework_commit": schema.framework_commit,
                    "model": schema.model,
                    "benchmark": schema.benchmark,
                    "metric_name": metric_name,
                    "mean": stats.mean,
                    "std": stats.std,
                    "n": stats.n,
                    "source_path": p,
                }
            )

    if rows:
        df = pl.DataFrame(rows)
    else:
        df = pl.DataFrame(
            schema={
                "framework": pl.Utf8,
                "framework_commit": pl.Utf8,
                "model": pl.Utf8,
                "benchmark": pl.Utf8,
                "metric_name": pl.Utf8,
                "mean": pl.Float64,
                "std": pl.Float64,
                "n": pl.Int64,
                "source_path": pl.Utf8,
            }
        )

    # Validate: each (framework, model, benchmark) cell must have one commit.
    if not df.is_empty():
        commit_groups = df.group_by(["framework", "model", "benchmark"]).agg(
            pl.col("framework_commit").unique().alias("commits")
        )
        for row in commit_groups.iter_rows(named=True):
            if len(row["commits"]) > 1:
                # Sort commits for deterministic error message; polars'
                # unique() does not guarantee insertion order across runs.
                commits = sorted(row["commits"])
                raise MixedCommitError(
                    f"{row['framework']}/{row['model']}/{row['benchmark']}: "
                    f"multiple commits {commits}"
                )

    return ResultsFrame(df=df, unloadable_count=unloadable)


def _format_cell(value: Optional[float], precision: int = 2) -> str:
    """Format a single numeric cell; em-dash for missing values."""
    if value is None or (
        isinstance(value, float) and value != value  # NaN check
    ):
        return r"\textit{--}"
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return str(value)


def _render_booktabs(
    df: pl.DataFrame,
    row_col: str,
    caption: str,
    label: str,
    precision: int = 2,
) -> Tuple[str, str]:
    """Render a polars DataFrame as a (fragment, standalone) LaTeX tuple.

    The first column is treated as the row label. All other columns are
    numeric data cells, rendered with the given precision; None/NaN ->
    em-dash.
    """
    cols = df.columns
    data_cols = [c for c in cols if c != row_col]

    lines: List[str] = []
    lines.append(r"\begin{tabular}{l" + "r" * len(data_cols) + "}")
    lines.append(r"\toprule")
    lines.append(" & ".join([row_col] + data_cols) + r" \\")
    lines.append(r"\midrule")
    for row in df.iter_rows(named=True):
        cells = [str(row[row_col])]
        for c in data_cols:
            cells.append(_format_cell(row[c], precision=precision))
        lines.append(" & ".join(cells) + r" \\")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    fragment = "\n".join(lines)

    standalone = (
        "\\documentclass{standalone}\n"
        "\\usepackage{booktabs}\n"
        "\\begin{document}\n"
        f"% caption: {caption}  label: {label}\n" + fragment + "\n"
        "\\end{document}\n"
    )
    return fragment, standalone


T1_FRAMEWORKS_ORDER = [
    "openclaw",
    "hermes",
    "openjarvis",
    "openjarvis-distilled",
]


def _build_t1(frame: ResultsFrame) -> Tuple[str, str]:
    """T1: Portability triangulation.

    Rows: 4 frameworks (in T1_FRAMEWORKS_ORDER).
    Cols: 8 benchmarks + Avg.
    Cells: accuracy mean (across all models in cell, weighted equally).
    """
    df = frame.df.filter(pl.col("metric_name") == "accuracy")
    pivot = (
        df.group_by(["framework", "benchmark"])
        .agg(pl.col("mean").mean().alias("acc"))
        .pivot(values="acc", index="framework", on="benchmark")
    )
    bench_cols = [c for c in pivot.columns if c != "framework"]
    if bench_cols:
        pivot = pivot.with_columns(
            pl.mean_horizontal(*[pl.col(c) for c in bench_cols]).alias("Avg")
        )
    return _render_booktabs(
        pivot,
        row_col="framework",
        caption="T1: Portability triangulation across frameworks (accuracy)",
        label="tab:t1_portability",
        precision=2,
    )


T2_METRICS = [
    ("latency_seconds", "Latency (s)"),
    ("energy_joules_per_query", "Energy (J)"),
    ("peak_power_w", "Power (W)"),
    ("input_tokens_per_query", "In tok"),
    ("output_tokens_per_query", "Out tok"),
    ("cost_usd_per_query", "$/query"),
]


def _build_t2(frame: ResultsFrame) -> Tuple[str, str]:
    """T2: Master efficiency comparison (mean across all benchmarks)."""
    df = frame.df.filter(pl.col("metric_name").is_in([m for m, _ in T2_METRICS]))
    pivot = (
        df.group_by(["framework", "model", "metric_name"])
        .agg(pl.col("mean").mean().alias("v"))
        .pivot(values="v", index=["framework", "model"], on="metric_name")
    )
    rename_map = {m: lbl for m, lbl in T2_METRICS if m in pivot.columns}
    pivot = pivot.rename(rename_map)
    pivot = pivot.with_columns(
        (pl.col("framework") + " + " + pl.col("model")).alias("Configuration")
    ).drop(["framework", "model"])
    ordered_cols = ["Configuration"] + [
        lbl for _, lbl in T2_METRICS if lbl in pivot.columns
    ]
    pivot = pivot.select(ordered_cols)
    return _render_booktabs(
        pivot,
        row_col="Configuration",
        caption="T2: Master efficiency comparison (per-query averages)",
        label="tab:t2_efficiency",
        precision=2,
    )


def _build_t3(frame: ResultsFrame) -> Tuple[str, str]:
    """T3: Per-benchmark efficiency (one detail panel — pick PinchBench)."""
    df = frame.df.filter(pl.col("benchmark") == "pinchbench")
    df = df.filter(
        pl.col("metric_name").is_in(
            [
                "latency_seconds",
                "energy_joules_per_query",
                "input_tokens_per_query",
                "output_tokens_per_query",
                "accuracy",
                "cost_usd_per_query",
            ]
        )
    )
    pivot = (
        df.group_by(["framework", "model", "metric_name"])
        .agg(pl.col("mean").mean().alias("v"))
        .pivot(values="v", index=["framework", "model"], on="metric_name")
    )
    pivot = pivot.with_columns(
        (pl.col("framework") + " + " + pl.col("model")).alias("Config")
    ).drop(["framework", "model"])
    return _render_booktabs(
        pivot,
        row_col="Config",
        caption="T3: PinchBench per-config efficiency",
        label="tab:t3_pb",
    )


def _build_t4(frame: ResultsFrame) -> Tuple[str, str]:
    """T4: 4-framework x all-model accuracy matrix (avg across benchmarks)."""
    df = frame.df.filter(pl.col("metric_name") == "accuracy")
    pivot = (
        df.group_by(["model", "framework"])
        .agg(pl.col("mean").mean().alias("acc"))
        .pivot(values="acc", index="model", on="framework")
    )
    return _render_booktabs(
        pivot,
        row_col="model",
        caption="T4: Per-model accuracy across frameworks",
        label="tab:t4_per_model",
    )


def _build_t5(frame: ResultsFrame) -> Tuple[str, str]:
    """T5: Hardware x framework efficiency (placeholder until per-hw data lands).

    Requires `hardware` field on the source summary.json (not yet wired into
    metrics). Until that lands, falls back to T2's shape so the cell is non-empty.
    """
    if "hardware" not in frame.df.columns:
        return _render_booktabs(
            pl.DataFrame({"Platform": ["(no data yet)"]}, schema={"Platform": pl.Utf8}),
            row_col="Platform",
            caption="T5: Hardware x framework efficiency (no data)",
            label="tab:t5_hw",
        )
    return _build_t2(frame)


def _build_t6(frame: ResultsFrame) -> Tuple[str, str]:
    """T6: Token economy decomposition (preliminary; total in/out only).

    Spec §6.3 envisions per-section breakdown (system_prompt, tool_descs,
    memory_rag, history, user_msg). Until that instrumentation lands, this
    only shows total in/out tokens per framework.
    """
    metrics = ["input_tokens_per_query", "output_tokens_per_query"]
    df = frame.df.filter(pl.col("metric_name").is_in(metrics))
    pivot = (
        df.group_by(["framework", "metric_name"])
        .agg(pl.col("mean").mean().alias("v"))
        .pivot(values="v", index="framework", on="metric_name")
    )
    return _render_booktabs(
        pivot,
        row_col="framework",
        caption="T6: Token economy (in/out per query)",
        label="tab:t6_tokens",
    )


def _build_t7(frame: ResultsFrame) -> Tuple[str, str]:
    """T7: Edit category x framework — preliminary (raw deltas).

    Spec §10 says richer edit-attribution data needs the spec-distillation
    pipeline to tag accepted edits. For now, raw per-benchmark accuracy
    deltas across frameworks.
    """
    df = frame.df.filter(pl.col("metric_name") == "accuracy")
    pivot = (
        df.group_by(["framework", "benchmark"])
        .agg(pl.col("mean").mean().alias("acc"))
        .pivot(values="acc", index="framework", on="benchmark")
    )
    return _render_booktabs(
        pivot,
        row_col="framework",
        caption="T7: Edit category x framework (preliminary; raw deltas)",
        label="tab:t7_edit",
    )


_TABLE_BUILDERS: Dict[str, "object"] = {
    "T1": _build_t1,
    "T2": _build_t2,
    "T3": _build_t3,
    "T4": _build_t4,
    "T5": _build_t5,
    "T6": _build_t6,
    "T7": _build_t7,
}


def _table_gen_default_output_dir() -> Path:
    return Path("experiments/framework_comparison/tables")


@click.command()
@click.option(
    "--results-glob",
    required=True,
    help='Glob, e.g. "results/comparison/**/summary.json"',
)
@click.option(
    "--tables",
    default="T1,T2,T3,T4,T5,T6,T7",
    help="Comma-separated list of table names to build",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory (default: experiments/framework_comparison/tables/)",
)
def main(results_glob: str, tables: str, output_dir: Optional[Path]) -> None:
    """Build LaTeX tables from framework-comparison evaluation results."""
    out = output_dir or _table_gen_default_output_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "preview").mkdir(parents=True, exist_ok=True)

    frame = load_results(results_glob)
    click.echo(
        f"Loaded {len(frame.df)} metric rows; {frame.unloadable_count} files skipped."
    )

    requested = [t.strip() for t in tables.split(",") if t.strip()]
    for name in requested:
        if name not in _TABLE_BUILDERS:
            click.echo(f"  ! unknown table {name}; skipping")
            continue
        try:
            fragment, standalone = _TABLE_BUILDERS[name](frame)
        except Exception as e:
            click.echo(f"  ! {name} build failed: {e}")
            continue
        (out / f"{name}.tex").write_text(fragment + "\n")
        (out / "preview" / f"{name}_preview.tex").write_text(standalone)
        click.echo(f"  ✓ {name} → {out}/{name}.tex (+ preview)")


if __name__ == "__main__":
    main()
