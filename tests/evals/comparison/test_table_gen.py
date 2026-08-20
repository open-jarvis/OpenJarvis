"""Tests for openjarvis.evals.comparison.table_gen."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from openjarvis.evals.comparison.table_gen import (  # noqa: E402
    MixedCommitError,
    ResultsFrame,
    load_results,
    main,
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

    def test_cli_refuses_empty_result_set(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        result = CliRunner().invoke(
            main,
            [
                "--results-glob",
                str(tmp_path / "**" / "summary.json"),
                "--tables",
                "T1",
                "--output-dir",
                str(tmp_path / "tables"),
            ],
        )
        assert result.exit_code != 0
        assert "No valid summary files matched" in result.output


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


class TestT1Builder:
    def test_t1_builds_from_synthetic_results(self) -> None:
        from openjarvis.evals.comparison.table_gen import (
            ResultsFrame,
            _build_t1,
        )

        df = pl.DataFrame(
            {
                "framework": [
                    "hermes",
                    "openjarvis",
                    "openclaw",
                    "openjarvis-distilled",
                ],
                "framework_commit": ["a", "b", "c", "b"],
                "model": ["qwen-9b"] * 4,
                "benchmark": ["gaia"] * 4,
                "metric_name": ["accuracy"] * 4,
                "mean": [0.22, 0.40, 0.20, 0.55],
                "std": [0.03] * 4,
                "n": [5] * 4,
                "source_path": ["x", "y", "z", "w"],
            }
        )
        frame = ResultsFrame(df=df)
        fragment, standalone = _build_t1(frame)
        assert "\\begin{tabular}" in fragment
        assert "0.22" in fragment or "22.00" in fragment
        assert "openjarvis-distilled" in fragment.lower() or "OJ-distilled" in fragment


class TestT2Builder:
    def test_t2_emits_efficiency_table(self) -> None:
        from openjarvis.evals.comparison.table_gen import (
            ResultsFrame,
            _build_t2,
        )

        rows = []
        for fwk, model in [
            ("hermes", "qwen-9b"),
            ("openjarvis", "qwen-9b"),
            ("hermes", "claude-opus-46"),
            ("openjarvis", "claude-opus-46"),
        ]:
            for metric, mean in [
                ("latency_seconds", 5.0),
                ("energy_joules_per_query", 100.0),
                ("input_tokens_per_query", 1000),
                ("output_tokens_per_query", 200),
                ("cost_usd_per_query", 0.001),
            ]:
                rows.append(
                    {
                        "framework": fwk,
                        "framework_commit": "x",
                        "model": model,
                        "benchmark": "gaia",
                        "metric_name": metric,
                        "mean": float(mean),
                        "std": 0.1,
                        "n": 5,
                        "source_path": "p",
                    }
                )
        frame = ResultsFrame(df=pl.DataFrame(rows))
        fragment, _ = _build_t2(frame)
        assert "\\begin{tabular}" in fragment
        assert "Latency" in fragment or "latency" in fragment
        assert "Energy" in fragment or "energy" in fragment


class TestT3to7Builders:
    """One smoke test per T3-T7 builder; each verifies tabular emission."""

    @pytest.mark.parametrize(
        "builder_name",
        ["_build_t3", "_build_t4", "_build_t5", "_build_t6", "_build_t7"],
    )
    def test_builder_emits_tabular(self, builder_name: str) -> None:
        import openjarvis.evals.comparison.table_gen as m

        builder = getattr(m, builder_name)
        rows = []
        for fwk in ["hermes", "openjarvis"]:
            for bench in ["gaia", "pinchbench"]:
                for metric in [
                    "accuracy",
                    "latency_seconds",
                    "energy_joules_per_query",
                    "input_tokens_per_query",
                    "output_tokens_per_query",
                    "cost_usd_per_query",
                ]:
                    rows.append(
                        {
                            "framework": fwk,
                            "framework_commit": "x",
                            "model": "qwen-9b",
                            "benchmark": bench,
                            "metric_name": metric,
                            "mean": 1.0,
                            "std": 0.1,
                            "n": 5,
                            "source_path": "p",
                        }
                    )
        frame = m.ResultsFrame(df=pl.DataFrame(rows))
        fragment, _ = builder(frame)
        assert "\\begin{tabular}" in fragment
        assert "\\end{tabular}" in fragment


class TestTableBuilderRegistry:
    def test_registry_has_all_seven(self) -> None:
        from openjarvis.evals.comparison.table_gen import _TABLE_BUILDERS

        assert set(_TABLE_BUILDERS.keys()) == {
            "T1",
            "T2",
            "T3",
            "T4",
            "T5",
            "T6",
            "T7",
        }


class TestTableGenCLI:
    def test_cli_writes_fragment_and_preview(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from openjarvis.evals.comparison.table_gen import main

        results_dir = tmp_path / "results"
        results_dir.mkdir()
        summary = results_dir / "summary.json"
        _write_summary(summary)

        out_dir = tmp_path / "tables"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--results-glob",
                str(results_dir / "**" / "summary.json"),
                "--tables",
                "T1",
                "--output-dir",
                str(out_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "T1.tex").exists()
        assert (out_dir / "preview" / "T1_preview.tex").exists()
        assert "\\begin{tabular}" in (out_dir / "T1.tex").read_text()
