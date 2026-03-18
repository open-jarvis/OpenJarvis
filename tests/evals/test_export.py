"""Tests for eval export utilities."""

from __future__ import annotations

import json

from openjarvis.evals.core.export import (
    _compute_efficiency,
    _compute_normalized,
    export_artifacts_manifest,
    export_jsonl,
    export_summary_json,
)
from openjarvis.evals.core.trace import QueryTrace, TurnTrace


def _make_traces(n=3):
    traces = []
    for i in range(n):
        traces.append(
            QueryTrace(
                query_id=f"q{i:04d}",
                workload_type="test",
                query_text=f"Question {i}",
                response_text=f"Answer {i}",
                turns=[
                    TurnTrace(
                        turn_index=0,
                        input_tokens=100 + i * 10,
                        output_tokens=50 + i * 5,
                        wall_clock_s=1.0 + i * 0.5,
                        gpu_energy_joules=5.0 + i,
                        cost_usd=0.01,
                    ),
                ],
                total_wall_clock_s=1.0 + i * 0.5,
                completed=True,
                is_resolved=i % 2 == 0,
            )
        )
    return traces


class TestExportJsonl:
    def test_basic_export(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "traces.jsonl"
        result = export_jsonl(traces, path)
        assert result == path
        assert path.exists()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            d = json.loads(line)
            assert "query_id" in d
            assert "turns" in d

    def test_empty_traces(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        export_jsonl([], path)
        assert path.read_text() == ""

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "c" / "traces.jsonl"
        export_jsonl(_make_traces(1), path)
        assert path.exists()


class TestExportSummaryJson:
    def test_basic_summary(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        result = export_summary_json(traces, {"model": "test"}, path)
        assert result == path
        assert path.exists()

        summary = json.loads(path.read_text())
        assert summary["totals"]["queries"] == 3
        assert summary["totals"]["completed"] == 3
        assert summary["totals"]["resolved"] == 2
        assert summary["totals"]["input_tokens"] > 0
        assert summary["totals"]["output_tokens"] > 0
        assert summary["config"]["model"] == "test"
        assert "statistics" in summary

    def test_statistics_keys(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        stats = summary["statistics"]
        expected_stat_keys = {
            "wall_clock_s",
            "gpu_energy_joules",
            "cpu_energy_joules",
            "gpu_power_watts",
            "cpu_power_watts",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "throughput_tokens_per_sec",
            "energy_per_token_joules",
            "cost_usd",
            "turns",
            "tool_calls",
            "mbu_avg_pct",
        }
        assert set(stats.keys()) == expected_stat_keys

    def test_agg_stats_fields(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        wc_stats = summary["statistics"]["wall_clock_s"]
        assert "avg" in wc_stats
        assert "median" in wc_stats
        assert "min" in wc_stats
        assert "max" in wc_stats
        assert "std" in wc_stats

    def test_empty_traces(self, tmp_path):
        path = tmp_path / "summary.json"
        export_summary_json([], {}, path)
        summary = json.loads(path.read_text())
        assert summary["totals"]["queries"] == 0


class TestExportArtifactsManifest:
    def test_no_artifacts_dir(self, tmp_path):
        result = export_artifacts_manifest(tmp_path)
        assert result is None

    def test_with_artifacts(self, tmp_path):
        art_dir = tmp_path / "artifacts"
        q_dir = art_dir / "q0001_test"
        q_dir.mkdir(parents=True)
        (q_dir / "response.txt").write_text("hello")
        (q_dir / "metadata.json").write_text("{}")

        result = export_artifacts_manifest(tmp_path)
        assert result is not None
        assert result.exists()

        manifest = json.loads(result.read_text())
        assert len(manifest) == 1
        assert manifest[0]["query_dir"] == "q0001_test"
        assert len(manifest[0]["files"]) == 2


class TestComputeEfficiency:
    def test_with_resolved_traces(self):
        traces = _make_traces()
        result = _compute_efficiency(traces, 15.0, 3.0)
        # 2 resolved out of 3 scored (is_resolved=True for i=0,2; False for i=1)
        assert result["accuracy"] == 2 / 3
        assert result["total_gpu_energy_joules"] == 15.0
        assert result["total_cpu_energy_joules"] == 3.0
        assert result["ipj"] is not None
        assert result["ipw"] is None  # no gpu power data on traces

    def test_no_scored_traces(self):
        traces = [
            QueryTrace(
                query_id="q0",
                workload_type="test",
                completed=True,
                is_resolved=None,
            ),
        ]
        result = _compute_efficiency(traces, 5.0, 1.0)
        assert result["accuracy"] is None
        assert result["ipj"] is None

    def test_no_energy(self):
        traces = _make_traces(1)
        result = _compute_efficiency(traces, None, None)
        assert result["total_gpu_energy_joules"] is None
        assert result["ipj"] is None

    def test_with_gpu_power(self):
        traces = [
            QueryTrace(
                query_id="q0",
                workload_type="test",
                completed=True,
                is_resolved=True,
                query_gpu_power_avg_watts=100.0,
            ),
        ]
        result = _compute_efficiency(traces, 50.0, None)
        assert result["accuracy"] == 1.0
        assert result["avg_gpu_power_watts"] == 100.0
        assert result["ipw"] == 1.0 / 100.0


class TestComputeNormalized:
    def test_too_few_traces(self):
        traces = _make_traces(3)
        assert _compute_normalized(traces) is None

    def test_with_enough_traces(self):
        traces = _make_traces(10)
        result = _compute_normalized(traces)
        assert result is not None
        norm_stats = result["normalized_statistics"]
        norm_eff = result["normalized_efficiency"]
        assert "_description" in norm_stats
        assert "_outliers_removed" in norm_stats
        assert norm_stats["_outliers_removed"] == 2  # 1 from each end
        assert "wall_clock_s" in norm_stats
        assert "mbu_avg_pct" in norm_stats
        assert "accuracy" in norm_eff

    def test_large_set_trims_more(self):
        traces = _make_traces(40)
        result = _compute_normalized(traces)
        assert result is not None
        # floor(40*0.05)=2 from each end
        assert result["normalized_statistics"]["_outliers_removed"] == 4


class TestExportSummaryJsonNewSections:
    def test_totals_accuracy(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        assert "accuracy" in summary["totals"]
        assert summary["totals"]["accuracy"] == 2 / 3

    def test_efficiency_section(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        assert "efficiency" in summary
        eff = summary["efficiency"]
        assert "accuracy" in eff
        assert "total_gpu_energy_joules" in eff
        assert "ipj" in eff
        assert "ipw" in eff

    def test_mbu_avg_pct_in_statistics(self, tmp_path):
        traces = _make_traces()
        traces[0].query_mbu_avg_pct = 45.0
        traces[1].query_mbu_avg_pct = 55.0
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        mbu_stats = summary["statistics"]["mbu_avg_pct"]
        assert mbu_stats["avg"] == 50.0

    def test_normalized_present_for_enough_traces(self, tmp_path):
        traces = _make_traces(10)
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        assert "normalized_statistics" in summary
        assert "normalized_efficiency" in summary

    def test_normalized_absent_for_few_traces(self, tmp_path):
        traces = _make_traces(3)
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        assert "normalized_statistics" not in summary
        assert "normalized_efficiency" not in summary

    def test_bench_telemetry(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        bench_energy = {"total_energy_joules": 100.0, "avg_power_watts": 50.0}
        export_summary_json(traces, {}, path, bench_energy=bench_energy)
        summary = json.loads(path.read_text())
        assert "bench_telemetry" in summary
        assert summary["bench_telemetry"]["total_energy_joules"] == 100.0

    def test_no_bench_telemetry_when_none(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        assert "bench_telemetry" not in summary


class TestQueryTraceMbuRoundTrip:
    def test_mbu_serialization(self):
        trace = QueryTrace(
            query_id="q0",
            workload_type="test",
            query_mbu_avg_pct=42.5,
            query_mbu_max_pct=87.3,
        )
        d = trace.to_dict()
        assert d["query_mbu_avg_pct"] == 42.5
        assert d["query_mbu_max_pct"] == 87.3

        restored = QueryTrace.from_dict(d)
        assert restored.query_mbu_avg_pct == 42.5
        assert restored.query_mbu_max_pct == 87.3

    def test_mbu_none_by_default(self):
        trace = QueryTrace(query_id="q0", workload_type="test")
        d = trace.to_dict()
        assert d["query_mbu_avg_pct"] is None
        assert d["query_mbu_max_pct"] is None

        restored = QueryTrace.from_dict(d)
        assert restored.query_mbu_avg_pct is None
        assert restored.query_mbu_max_pct is None

    def test_mbu_in_hf_dataset_rows(self):
        trace = QueryTrace(
            query_id="q0",
            workload_type="test",
            query_mbu_avg_pct=33.3,
            query_mbu_max_pct=66.6,
        )
        # Test that to_dict includes the fields (hf_dataset uses to_dict internally)
        d = trace.to_dict()
        assert "query_mbu_avg_pct" in d
        assert "query_mbu_max_pct" in d


class TestActionEnergyBreakdown:
    def test_turn_trace_round_trip(self):
        breakdown = [
            {
                "action_type": "lm_inference",
                "duration_s": 1.5,
                "gpu_energy_joules": 10.0,
                "cpu_energy_joules": 0.5,
            },
            {
                "action_type": "tool_call:calculator",
                "duration_s": 0.2,
                "gpu_energy_joules": 0.1,
                "cpu_energy_joules": 0.01,
            },
        ]
        turn = TurnTrace(
            turn_index=0,
            action_energy_breakdown=breakdown,
        )
        d = turn.to_dict()
        assert d["action_energy_breakdown"] is not None
        assert len(d["action_energy_breakdown"]) == 2
        assert d["action_energy_breakdown"][0]["action_type"] == "lm_inference"

        restored = TurnTrace.from_dict(d)
        assert restored.action_energy_breakdown is not None
        assert len(restored.action_energy_breakdown) == 2
        action_type = restored.action_energy_breakdown[1]["action_type"]
        assert action_type == "tool_call:calculator"

    def test_turn_trace_none_by_default(self):
        turn = TurnTrace(turn_index=0)
        d = turn.to_dict()
        assert d["action_energy_breakdown"] is None

        restored = TurnTrace.from_dict(d)
        assert restored.action_energy_breakdown is None

    def test_action_energy_summary_in_export(self, tmp_path):
        traces = []
        for i in range(2):
            traces.append(
                QueryTrace(
                    query_id=f"q{i:04d}",
                    workload_type="test",
                    turns=[
                        TurnTrace(
                            turn_index=0,
                            input_tokens=100,
                            output_tokens=50,
                            wall_clock_s=2.0,
                            gpu_energy_joules=5.0,
                            action_energy_breakdown=[
                                {
                                    "action_type": "lm_inference",
                                    "duration_s": 1.5,
                                    "gpu_energy_joules": 4.0,
                                    "cpu_energy_joules": 0.3,
                                },
                                {
                                    "action_type": "tool_call:search",
                                    "duration_s": 0.5,
                                    "gpu_energy_joules": 1.0,
                                    "cpu_energy_joules": 0.1,
                                },
                            ],
                        ),
                    ],
                    total_wall_clock_s=2.0,
                    completed=True,
                )
            )
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        assert "action_energy_summary" in summary
        aes = summary["action_energy_summary"]
        assert "lm_inference" in aes
        assert aes["lm_inference"]["count"] == 2
        assert aes["lm_inference"]["total_gpu_energy_joules"] == 8.0
        assert "tool_call:search" in aes
        assert aes["tool_call:search"]["count"] == 2

    def test_no_action_energy_summary_when_empty(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        assert "action_energy_summary" not in summary


class TestHardwareInfo:
    def test_hardware_info_in_summary(self, tmp_path):
        traces = _make_traces()
        path = tmp_path / "summary.json"
        export_summary_json(traces, {}, path)
        summary = json.loads(path.read_text())
        assert "hardware_info" in summary
        hw = summary["hardware_info"]
        # Should have at least platform and cpu_count
        assert "platform" in hw
        assert "cpu_count" in hw
        assert hw["cpu_count"] > 0
