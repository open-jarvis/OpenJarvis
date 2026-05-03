"""Tests for openjarvis.evals.comparison.table_gen."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from openjarvis.evals.comparison.table_gen import (
    MixedCommitError,
    ResultsFrame,
    load_results,
)


def _write_summary(path: Path, **overrides: object) -> None:
    payload = {
        "framework": "hermes",
        "framework_commit": "abc123",
        "model": "Qwen/Qwen3.5-9B",
        "benchmark": "gaia",
        "n_tasks": 50,
        "metrics": {
            "accuracy": {"mean": 0.42, "std": 0.04, "n": 5},
            "latency_seconds": {"mean": 23.4, "std": 5.1, "n": 5},
        },
        "per_sample": [],
        "hardware": {"gpu": "H100"},
        "started_at": "2026-05-01T00:00:00Z",
        "ended_at": "2026-05-01T01:00:00Z",
    }
    payload.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


class TestLoadResults:
    def test_loads_glob_and_returns_long_frame(self, tmp_path: Path) -> None:
        _write_summary(tmp_path / "a" / "summary.json", framework="hermes")
        _write_summary(
            tmp_path / "b" / "summary.json",
            framework="openclaw",
            framework_commit="def456",
        )

        frame = load_results(str(tmp_path / "**" / "summary.json"))
        assert isinstance(frame, ResultsFrame)
        # 2 files x 2 metrics each = 4 rows
        assert len(frame.df) == 4
        assert set(frame.df["framework"].to_list()) == {"hermes", "openclaw"}

    def test_skips_malformed_files(self, tmp_path: Path) -> None:
        good = tmp_path / "good" / "summary.json"
        _write_summary(good)
        bad = tmp_path / "bad" / "summary.json"
        bad.parent.mkdir(parents=True)
        bad.write_text("not json")

        frame = load_results(str(tmp_path / "**" / "summary.json"))
        # 1 good file x 2 metrics
        assert len(frame.df) == 2
        assert frame.unloadable_count == 1

    def test_mixed_commits_per_cell_raises(self, tmp_path: Path) -> None:
        _write_summary(tmp_path / "a" / "summary.json", framework_commit="abc123")
        _write_summary(tmp_path / "b" / "summary.json", framework_commit="zzz999")
        with pytest.raises(MixedCommitError, match="abc123.*zzz999"):
            load_results(str(tmp_path / "**" / "summary.json"))


class TestRenderBooktabs:
    def test_emits_valid_tabular(self) -> None:
        from openjarvis.evals.comparison.table_gen import _render_booktabs

        df = pl.DataFrame(
            {
                "row": ["hermes", "openjarvis"],
                "col1": [0.42, 0.55],
                "col2": [0.30, 0.40],
            }
        )
        fragment, standalone = _render_booktabs(
            df,
            row_col="row",
            caption="Test caption",
            label="tab:test",
        )
        assert "\\begin{tabular}" in fragment
        assert "\\end{tabular}" in fragment
        assert "hermes" in fragment and "openjarvis" in fragment
        assert "0.42" in fragment
        assert "\\documentclass{standalone}" in standalone
        assert fragment in standalone

    def test_missing_cell_renders_em_dash(self) -> None:
        from openjarvis.evals.comparison.table_gen import _render_booktabs

        df = pl.DataFrame(
            {
                "row": ["hermes", "openjarvis"],
                "col1": [None, 0.55],
            },
            schema={"row": pl.Utf8, "col1": pl.Float64},
        )
        fragment, _ = _render_booktabs(
            df,
            row_col="row",
            caption="x",
            label="x",
        )
        assert "\\textit{--}" in fragment
