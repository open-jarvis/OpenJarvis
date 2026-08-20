"""Round-trip test: EvalRunner output -> table_gen reads it correctly.

Verifies that the schema emitted by `_summary_to_dict` (regular EvalRunner
path used by hermes/openclaw) and `export_summary_json` (agentic-runner
path) is consumable by `table_gen.load_results` without being skipped as
'unloadable'.

This was the critical gap caught in final review: components that worked
in isolation but didn't connect end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

from openjarvis.evals.comparison.table_gen import (
    _build_t1,
    load_results,
)


class TestExportToTableGenRoundtrip:
    def test_summary_json_loads_via_table_gen(self, tmp_path: Path) -> None:
        """Construct a summary.json mimicking _summary_to_dict output;
        verify table_gen.load_results parses it without skipping."""
        summary = {
            # Existing rich schema (unchanged)
            "hardware_info": {"gpu": "H100"},
            "benchmark": "gaia",
            "model": "Qwen/Qwen3.5-9B",
            "backend": "hermes",
            "category": "agentic",
            "total_samples": 50,
            "scored_samples": 50,
            "correct": 21,
            "accuracy": 0.42,
            "errors": 0,
            "mean_latency_seconds": 23.4,
            "total_cost_usd": 0.7,
            # New §6.3-compatible fields
            "framework": "hermes",
            "framework_commit": "5d3be898a",
            "n_tasks": 50,
            "metrics": {
                "accuracy": {"mean": 0.42, "std": 0.04, "n": 50},
                "latency_seconds": {"mean": 23.4, "std": 5.1, "n": 50},
                "energy_joules_per_query": {
                    "mean": 1234.5,
                    "std": 90,
                    "n": 50,
                },
                "input_tokens_per_query": {
                    "mean": 5432,
                    "std": 200,
                    "n": 50,
                },
                "output_tokens_per_query": {
                    "mean": 845,
                    "std": 50,
                    "n": 50,
                },
                "cost_usd_per_query": {
                    "mean": 0.014,
                    "std": 0.002,
                    "n": 50,
                },
            },
        }
        path = tmp_path / "summary.json"
        path.write_text(json.dumps(summary))

        frame = load_results(str(tmp_path / "**" / "summary.json"))
        # Should NOT be skipped as unloadable
        assert frame.unloadable_count == 0
        # Should have one row per metric (6 metrics here)
        assert len(frame.df) == 6
        # Verify framework/commit propagated
        assert frame.df["framework"].to_list()[0] == "hermes"
        assert frame.df["framework_commit"].to_list()[0] == "5d3be898a"

    def test_table_gen_builds_t1_from_export_schema(self, tmp_path: Path) -> None:
        """T1 builder produces non-empty LaTeX from realistic schema."""
        for fwk, acc in [("hermes", 0.30), ("openjarvis", 0.45)]:
            summary = {
                "framework": fwk,
                "framework_commit": "abc" if fwk == "hermes" else "def",
                "model": "Qwen/Qwen3.5-9B",
                "benchmark": "gaia",
                "n_tasks": 50,
                "metrics": {
                    "accuracy": {"mean": acc, "std": 0.04, "n": 50},
                },
            }
            (tmp_path / fwk).mkdir()
            (tmp_path / fwk / "summary.json").write_text(json.dumps(summary))

        frame = load_results(str(tmp_path / "**" / "summary.json"))
        fragment, _ = _build_t1(frame)
        assert "\\begin{tabular}" in fragment
        assert "0.30" in fragment
        assert "0.45" in fragment


class TestSummaryToDictEmitsRequiredFields:
    """Verify `_summary_to_dict` emits the §6.3 fields when given results.

    `_summary_to_dict` is the dict-builder used by EvalRunner to write
    `.summary.json` for non-agentic runs (the path hermes/openclaw take).
    """

    def test_summary_to_dict_includes_table_gen_fields(self) -> None:
        from openjarvis.evals.core.runner import _summary_to_dict
        from openjarvis.evals.core.types import EvalResult, RunSummary

        results = [
            EvalResult(
                record_id=f"q{i}",
                model_answer=f"answer-{i}",
                latency_seconds=2.0 + i * 0.1,
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.001,
                energy_joules=10.0,
                power_watts=30.0,
                framework="hermes",
                framework_commit="5d3be898a",
                tool_calls=2,
                turn_count=3,
                is_correct=(i % 2 == 0),
            )
            for i in range(5)
        ]

        summary = RunSummary(
            benchmark="gaia",
            category="agentic",
            backend="hermes",
            model="Qwen/Qwen3.5-9B",
            total_samples=5,
            scored_samples=5,
            correct=3,
            accuracy=0.6,
            errors=0,
            mean_latency_seconds=2.2,
            total_cost_usd=0.005,
        )

        d = _summary_to_dict(summary, results=results)

        # New §6.3-compatible top-level fields
        assert d["framework"] == "hermes"
        assert d["framework_commit"] == "5d3be898a"
        assert d["model"] == "Qwen/Qwen3.5-9B"
        assert d["benchmark"] == "gaia"
        assert d["n_tasks"] == 5
        assert "accuracy" in d["metrics"]
        assert "latency_seconds" in d["metrics"]
        assert d["metrics"]["peak_power_w"]["mean"] == 30.0
        assert d["metrics"]["accuracy"]["n"] == 5
        assert d["metrics"]["latency_seconds"]["n"] == 5
        # Existing rich schema also present (unchanged)
        assert "hardware_info" in d
        assert "telemetry_summary" in d

    def test_summary_to_dict_without_results_still_works(self) -> None:
        """Backward compat: calling without ``results`` must not error."""
        from openjarvis.evals.core.runner import _summary_to_dict
        from openjarvis.evals.core.types import RunSummary

        summary = RunSummary(
            benchmark="gaia",
            category="agentic",
            backend="hermes",
            model="m",
            total_samples=0,
            scored_samples=0,
            correct=0,
            accuracy=0.0,
            errors=0,
            mean_latency_seconds=0.0,
            total_cost_usd=0.0,
        )

        d = _summary_to_dict(summary)
        # Still emits the §6.3 keys (defaults), so the schema is stable.
        assert d["framework"] == "openjarvis"
        assert d["n_tasks"] == 0
        assert d["metrics"]["accuracy"] == {"mean": 0.0, "std": 0.0, "n": 0}


class TestExportSummaryJsonEmitsRequiredFields:
    """Verify `export_summary_json` (the agentic-runner path) also emits
    the §6.3 fields, sourced from the ``config`` dict argument."""

    def test_export_summary_includes_table_gen_fields(self, tmp_path: Path) -> None:
        from openjarvis.evals.core.export import export_summary_json
        from openjarvis.evals.core.trace import QueryTrace, TurnTrace

        # Build minimal traces with enough fields populated so the
        # statistics blocks are non-empty.
        traces = []
        for i in range(5):
            turn = TurnTrace(
                turn_index=0,
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.001,
                gpu_energy_joules=10.0,
                gpu_power_avg_watts=20.0,
            )
            t = QueryTrace(
                query_id=f"q{i}",
                workload_type="agentic",
                turns=[turn],
                total_wall_clock_s=2.0 + i * 0.1,
                completed=True,
                is_resolved=(i % 2 == 0),
            )
            traces.append(t)

        out_path = tmp_path / "summary.json"
        export_summary_json(
            traces,
            config={
                "model": "Qwen/Qwen3.5-9B",
                "benchmark": "gaia",
                "framework": "hermes",
                "framework_commit": "5d3be898a",
            },
            path=out_path,
        )

        data = json.loads(out_path.read_text())
        # New §6.3-compatible fields
        assert data["framework"] == "hermes"
        assert data["framework_commit"] == "5d3be898a"
        assert data["model"] == "Qwen/Qwen3.5-9B"
        assert data["benchmark"] == "gaia"
        assert data["n_tasks"] == 5
        assert "accuracy" in data["metrics"]
        assert "latency_seconds" in data["metrics"]
        assert data["metrics"]["accuracy"]["n"] > 0
        # Existing rich schema also present (unchanged)
        assert "generated_at" in data
        assert "totals" in data
