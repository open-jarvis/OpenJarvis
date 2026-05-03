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
from typing import Dict, List

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
