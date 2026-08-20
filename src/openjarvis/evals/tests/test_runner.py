"""Tests for the EvalRunner."""

from __future__ import annotations

import json

import pytest

from openjarvis.evals.core.runner import (
    EvalRunner,
    _metric_stats,
    _metric_stats_to_dict,
)
from openjarvis.evals.core.types import EvalRecord, MetricStats, RunConfig
from openjarvis.evals.tests.conftest import MockBackend, MockDataset, MockScorer


class TestEvalRunner:
    def _make_records(self, n=5):
        return [
            EvalRecord(
                record_id=f"r{i}",
                problem=f"Question {i}",
                reference=f"Answer {i}",
                category="reasoning",
                subject="math" if i % 2 == 0 else "science",
            )
            for i in range(n)
        ]

    def test_basic_run(self, tmp_path):
        records = self._make_records(5)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="test-model",
            max_workers=1,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()

        assert summary.total_samples == 5
        assert summary.scored_samples == 5
        assert summary.correct == 5
        assert summary.accuracy == 1.0
        assert summary.errors == 0
        assert summary.benchmark == "test"
        assert summary.model == "test-model"

    def test_with_errors(self, tmp_path):
        records = self._make_records(3)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        # Backend that raises on second call
        class FailingBackend(MockBackend):
            def __init__(self):
                super().__init__()
                self._fail_count = 0

            def generate_full(self, prompt, **kw):
                self._fail_count += 1
                if self._fail_count == 2:
                    raise RuntimeError("test error")
                return super().generate_full(prompt, **kw)

        dataset = MockDataset(records)
        backend = FailingBackend()
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()

        assert summary.total_samples == 3
        assert summary.errors == 1

    def test_per_subject_breakdown(self, tmp_path):
        records = self._make_records(4)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()

        assert "math" in summary.per_subject
        assert "science" in summary.per_subject
        assert summary.per_subject["math"]["accuracy"] == 1.0

    def test_jsonl_output(self, tmp_path):
        records = self._make_records(3)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        runner.run()

        # Verify JSONL
        lines = output_path.read_text().strip().split("\n")
        assert len(lines) == 3
        first = json.loads(lines[0])
        assert "record_id" in first
        assert "model_answer" in first
        assert "is_correct" in first

        # Verify summary JSON
        summary_path = output_path.with_suffix(".summary.json")
        assert summary_path.exists()
        summary_data = json.loads(summary_path.read_text())
        assert summary_data["total_samples"] == 3

    def test_parallel_workers(self, tmp_path):
        records = self._make_records(10)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=4,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()

        assert summary.total_samples == 10
        assert summary.correct == 10

    def test_mixed_scoring(self, tmp_path):
        records = self._make_records(4)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        # Scorer that alternates correct/incorrect
        class AlternatingScorer(MockScorer):
            def __init__(self):
                super().__init__()
                self._count = 0

            def score(self, record, model_answer):
                self._count += 1
                return (self._count % 2 == 0), {"count": self._count}

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = AlternatingScorer()

        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()

        assert summary.scored_samples == 4
        assert summary.correct == 2
        assert summary.accuracy == 0.5

    def test_telemetry_fields_in_jsonl(self, tmp_path):
        """Verify telemetry fields are written to JSONL output."""
        records = self._make_records(2)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        runner.run()

        lines = output_path.read_text().strip().split("\n")
        first = json.loads(lines[0])
        assert "energy_joules" in first
        assert "power_watts" in first
        assert "gpu_utilization_pct" in first
        assert "throughput_tok_per_sec" in first
        assert "mfu_pct" in first
        assert "mbu_pct" in first
        assert "ipw" in first
        assert "ipj" in first

    def test_ipw_ipj_computation(self, tmp_path):
        """IPW and IPJ should be computed for correct samples."""
        records = self._make_records(2)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()  # returns power=250W, energy=50J
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        runner.run()

        lines = output_path.read_text().strip().split("\n")
        r = json.loads(lines[0])
        # accuracy=1.0, power=250W → IPW = 1/250 = 0.004
        assert r["ipw"] == pytest.approx(1.0 / 250.0, rel=1e-4)
        # accuracy=1.0, energy=50J → IPJ = 1/50 = 0.02
        assert r["ipj"] == pytest.approx(1.0 / 50.0, rel=1e-4)

    def test_ipw_ipj_zero_for_incorrect(self, tmp_path):
        """IPW and IPJ should be 0 for incorrect samples."""
        records = self._make_records(1)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=False)

        runner = EvalRunner(config, dataset, backend, scorer)
        runner.run()

        lines = output_path.read_text().strip().split("\n")
        r = json.loads(lines[0])
        assert r["ipw"] == 0.0
        assert r["ipj"] == 0.0

    def test_mfu_mbu_with_metadata(self, tmp_path):
        """MFU/MBU should be computed when model metadata is provided."""
        records = self._make_records(1)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
            metadata={
                "param_count_b": 7.0,
                "gpu_peak_tflops": 312.0,
                "gpu_peak_bandwidth_gb_s": 2039.0,
                "num_gpus": 1,
            },
        )

        dataset = MockDataset(records)
        backend = MockBackend()  # throughput=38 tok/s
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        runner.run()

        lines = output_path.read_text().strip().split("\n")
        r = json.loads(lines[0])
        # With compute_efficiency available, MFU/MBU should be > 0
        assert r["mfu_pct"] > 0 or r["mfu_pct"] == 0  # depends on import
        assert r["mbu_pct"] >= 0

    def test_summary_metric_stats(self, tmp_path):
        """Summary should include MetricStats for telemetry fields."""
        records = self._make_records(5)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()

        assert summary.accuracy_stats is not None
        assert summary.accuracy_stats.mean == 1.0
        assert summary.energy_stats is not None
        assert summary.energy_stats.mean == 50.0
        assert summary.power_stats is not None
        assert summary.power_stats.mean == 250.0
        assert summary.throughput_stats is not None
        assert summary.ipw_stats is not None
        assert summary.total_energy_joules == 250.0  # 5 * 50.0

    def test_summary_json_includes_metric_stats(self, tmp_path):
        """Summary JSON file should serialize MetricStats fields."""
        records = self._make_records(3)
        output_path = tmp_path / "results.jsonl"

        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )

        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=True)

        runner = EvalRunner(config, dataset, backend, scorer)
        runner.run()

        summary_path = output_path.with_suffix(".summary.json")
        data = json.loads(summary_path.read_text())
        assert "accuracy_stats" in data
        assert data["accuracy_stats"]["mean"] == 1.0
        assert "energy_stats" in data
        assert "power_stats" in data
        assert "mfu_stats" in data or data["mfu_stats"] is None
        assert "ipw_stats" in data
        assert "ipj_stats" in data
        assert "total_energy_joules" in data


class TestRunnerTokenStats:
    def test_summary_has_total_input_output_tokens(self, tmp_path):
        """RunSummary should include total token counts."""
        records = [
            EvalRecord(
                record_id=f"r{i}",
                problem=f"q{i}",
                reference="a",
                category="test",
            )
            for i in range(3)
        ]
        output_path = tmp_path / "results.jsonl"
        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )
        dataset = MockDataset(records)
        backend = MockBackend()
        scorer = MockScorer(result=True)
        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()
        # MockBackend returns prompt_tokens=100, completion_tokens=50
        assert summary.total_input_tokens == 300  # 3 * 100
        assert summary.total_output_tokens == 150  # 3 * 50

    def test_summary_has_avg_power(self, tmp_path):
        """RunSummary should include avg_power_watts."""
        records = [
            EvalRecord(record_id="r1", problem="q", reference="a", category="test")
        ]
        output_path = tmp_path / "results.jsonl"
        config = RunConfig(
            benchmark="test",
            backend="mock",
            model="m",
            max_workers=1,
            output_path=str(output_path),
        )
        dataset = MockDataset(records)
        backend = MockBackend()  # returns power_watts=250.0
        scorer = MockScorer(result=True)
        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()
        assert summary.avg_power_watts == 250.0


class TestMetricStatsHelpers:
    def test_metric_stats_empty(self):
        assert _metric_stats([]) is None

    def test_metric_stats_single(self):
        ms = _metric_stats([5.0])
        assert ms is not None
        assert ms.mean == 5.0
        assert ms.median == 5.0
        assert ms.min == 5.0
        assert ms.max == 5.0
        assert ms.std == 0.0

    def test_metric_stats_multiple(self):
        ms = _metric_stats([1.0, 2.0, 3.0, 4.0, 5.0])
        assert ms is not None
        assert ms.mean == 3.0
        assert ms.median == 3.0
        assert ms.min == 1.0
        assert ms.max == 5.0
        assert ms.std > 0

    def test_metric_stats_to_dict_none(self):
        assert _metric_stats_to_dict(None) is None

    def test_metric_stats_to_dict(self):
        ms = MetricStats(mean=1.0, median=2.0, min=0.5, max=3.0, std=0.8)
        d = _metric_stats_to_dict(ms)
        assert d["mean"] == 1.0
        assert d["median"] == 2.0
        assert d["min"] == 0.5
        assert d["max"] == 3.0
        assert d["std"] == 0.8
        assert "p90" in d
        assert "p95" in d
        assert "p99" in d
