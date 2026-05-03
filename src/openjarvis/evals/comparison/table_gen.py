"""LaTeX table generator for the NeurIPS 2026 framework-comparison experiment.

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

import polars as pl
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
                raise MixedCommitError(
                    f"{row['framework']}/{row['model']}/{row['benchmark']}: "
                    f"multiple commits {row['commits']}"
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
