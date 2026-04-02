"""Tests for telemetry wiring in the eval pipeline.

Verifies that:
- FLOPs estimation flows from config metadata through to EvalResult and RunSummary
- Telemetry fields (energy, power, GPU util) propagate end-to-end
- JarvisDirectBackend propagates gpu_metrics flag
- TauBench dataset passes telemetry flags to task env
- Summary JSON includes telemetry_summary section
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.evals.core.types import EvalResult, RunConfig, RunSummary

# ---------------------------------------------------------------------------
# FLOPs estimation in EvalResult
# ---------------------------------------------------------------------------


class TestEvalResultFlops:
    """Verify estimated_flops field exists and is serializable."""

    def test_default_zero(self):
        r = EvalResult(record_id="test", model_answer="hi")
        assert r.estimated_flops == 0.0

    def test_set_flops(self):
        flops = 2.0 * 10.0 * 1e9 * 1000  # 10B active params, 1000 tokens
        r = EvalResult(record_id="test", model_answer="hi", estimated_flops=flops)
        assert r.estimated_flops == flops

    def test_flops_in_dict(self):
        """EvalResult with estimated_flops can be serialized to JSON."""
        r = EvalResult(record_id="t", model_answer="a", estimated_flops=1e15)
        d = {"estimated_flops": r.estimated_flops}
        s = json.dumps(d)
        assert "1e+15" in s or "1000000000000000" in s


# ---------------------------------------------------------------------------
# RunSummary telemetry fields
# ---------------------------------------------------------------------------


class TestRunSummaryTelemetry:
    """Verify RunSummary includes FLOPs and telemetry aggregation fields."""

    def test_default_flops_fields(self):
        s = RunSummary(
            benchmark="test",
            category="chat",
            backend="jarvis-direct",
            model="test-model",
            total_samples=1,
            scored_samples=1,
            correct=1,
            accuracy=1.0,
            errors=0,
            mean_latency_seconds=1.0,
            total_cost_usd=0.0,
        )
        assert s.total_estimated_flops == 0.0
        assert s.flops_stats is None


# ---------------------------------------------------------------------------
# Runner _process_one FLOPs computation
# ---------------------------------------------------------------------------


class TestRunnerFlopsComputation:
    """Test that _process_one computes estimated_flops from model metadata."""

    def test_flops_computed_from_metadata(self):
        """When param_count_b is in metadata, FLOPs are estimated."""
        from openjarvis.evals.core.runner import EvalRunner
        from openjarvis.evals.core.types import EvalRecord

        config = RunConfig(
            benchmark="test",
            backend="jarvis-direct",
            model="test-model",
            metadata={
                "param_count_b": 7.0,
                "active_params_b": 7.0,
            },
        )

        mock_backend = MagicMock()
        mock_backend.generate_full.return_value = {
            "content": "answer",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "latency_seconds": 1.0,
            "cost_usd": 0.0,
        }

        mock_scorer = MagicMock()
        mock_scorer.score.return_value = (True, {})

        mock_dataset = MagicMock()
        runner = EvalRunner(config, mock_dataset, mock_backend, mock_scorer)

        record = EvalRecord(
            record_id="test-1",
            problem="What is 2+2?",
            reference="4",
            category="reasoning",
        )

        result = runner._process_one(record)

        # FLOPs = 2 * active_params * total_tokens
        # = 2 * 7e9 * 150 = 2.1e12
        expected_flops = 2.0 * 7.0 * 1e9 * 150
        assert result.estimated_flops == pytest.approx(expected_flops)

    def test_flops_zero_without_metadata(self):
        """When no param_count_b in metadata, FLOPs should be 0."""
        from openjarvis.evals.core.runner import EvalRunner
        from openjarvis.evals.core.types import EvalRecord

        config = RunConfig(
            benchmark="test",
            backend="jarvis-direct",
            model="test-model",
            metadata={},
        )

        mock_backend = MagicMock()
        mock_backend.generate_full.return_value = {
            "content": "answer",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "latency_seconds": 1.0,
            "cost_usd": 0.0,
        }

        mock_scorer = MagicMock()
        mock_scorer.score.return_value = (True, {})

        mock_dataset = MagicMock()
        runner = EvalRunner(config, mock_dataset, mock_backend, mock_scorer)

        record = EvalRecord(
            record_id="test-1",
            problem="What is 2+2?",
            reference="4",
            category="reasoning",
        )

        result = runner._process_one(record)
        assert result.estimated_flops == 0.0

    def test_flops_uses_active_params_for_moe(self):
        """For MoE models, FLOPs should use active_params_b, not total."""
        from openjarvis.evals.core.runner import EvalRunner
        from openjarvis.evals.core.types import EvalRecord

        config = RunConfig(
            benchmark="test",
            backend="jarvis-direct",
            model="test-model",
            metadata={
                "param_count_b": 122.0,
                "active_params_b": 10.0,
            },
        )

        mock_backend = MagicMock()
        mock_backend.generate_full.return_value = {
            "content": "answer",
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
            "latency_seconds": 1.0,
            "cost_usd": 0.0,
        }

        mock_scorer = MagicMock()
        mock_scorer.score.return_value = (True, {})

        mock_dataset = MagicMock()
        runner = EvalRunner(config, mock_dataset, mock_backend, mock_scorer)

        record = EvalRecord(
            record_id="test-1",
            problem="What is 2+2?",
            reference="4",
            category="reasoning",
        )

        result = runner._process_one(record)

        # Should use active_params_b=10.0, not param_count_b=122.0
        expected_flops = 2.0 * 10.0 * 1e9 * 300  # 300 total tokens
        assert result.estimated_flops == pytest.approx(expected_flops)


# ---------------------------------------------------------------------------
# Summary JSON telemetry_summary section
# ---------------------------------------------------------------------------


class TestSummaryToDict:
    """Test that _summary_to_dict includes the telemetry_summary section."""

    def test_telemetry_summary_present(self):
        from openjarvis.evals.core.runner import _summary_to_dict

        s = RunSummary(
            benchmark="test",
            category="chat",
            backend="jarvis-direct",
            model="test-model",
            total_samples=10,
            scored_samples=10,
            correct=8,
            accuracy=0.8,
            errors=0,
            mean_latency_seconds=2.0,
            total_cost_usd=0.1,
            total_energy_joules=50.0,
            avg_power_watts=25.0,
            total_input_tokens=5000,
            total_output_tokens=2000,
            total_estimated_flops=1.4e13,
            efficiency={
                "accuracy": 0.8,
                "total_energy_joules": 50.0,
                "avg_power_watts": 25.0,
                "total_estimated_flops": 1.4e13,
                "ipj": 0.016,
                "ipw": 0.032,
            },
        )

        d = _summary_to_dict(s)

        # Check telemetry_summary section exists
        assert "telemetry_summary" in d
        ts = d["telemetry_summary"]

        assert ts["total_energy_joules"] == 50.0
        assert ts["avg_power_watts"] == 25.0
        assert ts["total_input_tokens"] == 5000
        assert ts["total_output_tokens"] == 2000
        assert ts["total_tokens"] == 7000
        assert ts["total_estimated_flops"] == 1.4e13
        assert ts["ipw"] == 0.032
        assert ts["ipj"] == 0.016

    def test_flops_fields_in_summary_dict(self):
        from openjarvis.evals.core.runner import _summary_to_dict

        s = RunSummary(
            benchmark="test",
            category="chat",
            backend="jarvis-direct",
            model="test-model",
            total_samples=1,
            scored_samples=1,
            correct=1,
            accuracy=1.0,
            errors=0,
            mean_latency_seconds=1.0,
            total_cost_usd=0.0,
            total_estimated_flops=2.1e12,
        )

        d = _summary_to_dict(s)
        assert d["total_estimated_flops"] == 2.1e12
        assert "flops_stats" in d


# ---------------------------------------------------------------------------
# Flush result includes estimated_flops
# ---------------------------------------------------------------------------


class TestFlushResult:
    """Test that _flush_result includes estimated_flops in JSONL output."""

    def test_estimated_flops_in_jsonl(self, tmp_path):
        from openjarvis.evals.core.runner import EvalRunner

        config = RunConfig(
            benchmark="test",
            backend="jarvis-direct",
            model="test-model",
        )

        mock_backend = MagicMock()
        mock_scorer = MagicMock()
        mock_dataset = MagicMock()
        runner = EvalRunner(config, mock_dataset, mock_backend, mock_scorer)

        outfile = tmp_path / "results.jsonl"
        runner._output_file = open(outfile, "w")

        result = EvalResult(
            record_id="test-1",
            model_answer="answer",
            estimated_flops=2.1e12,
        )
        runner._flush_result(result)
        runner._output_file.close()
        runner._output_file = None

        lines = outfile.read_text().strip().split("\n")
        record = json.loads(lines[0])
        assert record["estimated_flops"] == 2.1e12


# ---------------------------------------------------------------------------
# Trace dict includes estimated_flops
# ---------------------------------------------------------------------------


class TestResultToTraceDict:
    """Test that _result_to_trace_dict includes estimated_flops."""

    def test_estimated_flops_in_trace(self):
        from openjarvis.evals.core.runner import _result_to_trace_dict

        result = EvalResult(
            record_id="test-1",
            model_answer="answer",
            estimated_flops=3.0e12,
        )

        d = _result_to_trace_dict(result)
        assert d["estimated_flops"] == 3.0e12


# ---------------------------------------------------------------------------
# JarvisDirectBackend gpu_metrics propagation
# ---------------------------------------------------------------------------


class TestDirectBackendGpuMetrics:
    """Verify JarvisDirectBackend sets gpu_metrics on config."""

    @patch("openjarvis.system.SystemBuilder")
    def test_gpu_metrics_propagated(self, mock_builder_cls):
        """When gpu_metrics=True, the builder config should be updated."""
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder
        mock_builder.engine.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder

        # Create a mock config with telemetry.gpu_metrics attribute
        mock_config = MagicMock()
        mock_config.telemetry.gpu_metrics = False
        mock_builder._config = mock_config

        mock_system = MagicMock()
        mock_builder.build.return_value = mock_system

        JarvisDirectBackend(
            engine_key="vllm",
            telemetry=True,
            gpu_metrics=True,
        )

        # Verify gpu_metrics was set to True on config
        assert mock_config.telemetry.gpu_metrics is True

    @patch("openjarvis.system.SystemBuilder")
    def test_gpu_metrics_not_set_when_false(self, mock_builder_cls):
        """When gpu_metrics=False, the builder config should not be touched."""
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder
        mock_builder.engine.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder

        mock_config = MagicMock()
        mock_config.telemetry.gpu_metrics = False
        mock_builder._config = mock_config

        mock_system = MagicMock()
        mock_builder.build.return_value = mock_system

        JarvisDirectBackend(
            engine_key="vllm",
            telemetry=False,
            gpu_metrics=False,
        )

        # When gpu_metrics is False, the attribute should still be False
        assert mock_config.telemetry.gpu_metrics is False


# ---------------------------------------------------------------------------
# TauBench telemetry flag passthrough
# ---------------------------------------------------------------------------


class TestTauBenchTelemetryPassthrough:
    """Verify TauBench dataset passes telemetry flags to task env."""

    def test_set_engine_config_stores_flags(self):
        """set_engine_config should store telemetry and gpu_metrics."""
        from openjarvis.evals.datasets.taubench import TauBenchDataset

        ds = TauBenchDataset.__new__(TauBenchDataset)
        ds._domains = ["airline"]
        ds._records = []
        ds._engine_key = None
        ds._model = None
        ds._temperature = 0.7
        ds._max_tokens = 4096
        ds._user_model = None
        ds._num_trials = 3
        ds._telemetry = False
        ds._gpu_metrics = False

        ds.set_engine_config(
            engine_key="vllm",
            model="test-model",
            telemetry=True,
            gpu_metrics=True,
        )

        assert ds._telemetry is True
        assert ds._gpu_metrics is True

    @patch("openjarvis.evals.execution.taubench_env.TauBenchTaskEnv")
    def test_create_task_env_passes_flags(self, mock_env_cls):
        """create_task_env should forward telemetry flags."""
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.datasets.taubench import TauBenchDataset

        ds = TauBenchDataset.__new__(TauBenchDataset)
        ds._domains = ["airline"]
        ds._records = []
        ds._engine_key = "vllm"
        ds._model = "test-model"
        ds._temperature = 0.7
        ds._max_tokens = 4096
        ds._user_model = None
        ds._num_trials = 3
        ds._telemetry = True
        ds._gpu_metrics = True

        record = EvalRecord(
            record_id="airline_1",
            problem="test",
            reference="test",
            category="airline",
            metadata={"domain": "airline", "task_id": "1"},
        )

        ds.create_task_env(record)

        mock_env_cls.assert_called_once_with(
            record,
            engine_key="vllm",
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            user_model=None,
            num_trials=3,
            telemetry=True,
            gpu_metrics=True,
        )


# ---------------------------------------------------------------------------
# RunConfig expand_suite preserves model metadata for FLOPs
# ---------------------------------------------------------------------------


class TestExpandSuiteModelMetadata:
    """Verify expand_suite passes param_count_b and active_params_b to RunConfig."""

    def test_metadata_includes_params(self):
        from openjarvis.evals.core.config import expand_suite
        from openjarvis.evals.core.types import (
            BenchmarkConfig,
            DefaultsConfig,
            EvalSuiteConfig,
            ExecutionConfig,
            JudgeConfig,
            MetaConfig,
            ModelConfig,
        )

        suite = EvalSuiteConfig(
            meta=MetaConfig(name="test"),
            defaults=DefaultsConfig(),
            judge=JudgeConfig(),
            run=ExecutionConfig(telemetry=True, gpu_metrics=True),
            models=[
                ModelConfig(
                    name="test/moe-model",
                    param_count_b=122.0,
                    active_params_b=10.0,
                    gpu_peak_tflops=989.5,
                    gpu_peak_bandwidth_gb_s=3350.0,
                    num_gpus=4,
                ),
            ],
            benchmarks=[
                BenchmarkConfig(name="math500"),
            ],
        )

        configs = expand_suite(suite)
        assert len(configs) == 1

        rc = configs[0]
        assert rc.telemetry is True
        assert rc.gpu_metrics is True
        assert rc.metadata["param_count_b"] == 122.0
        assert rc.metadata["active_params_b"] == 10.0
        assert rc.metadata["gpu_peak_tflops"] == 989.5
        assert rc.metadata["gpu_peak_bandwidth_gb_s"] == 3350.0
        assert rc.metadata["num_gpus"] == 4


# ---------------------------------------------------------------------------
# Telemetry data flow from backend through runner
# ---------------------------------------------------------------------------


class TestTelemetryEndToEnd:
    """Test full telemetry data flow from backend to EvalResult."""

    def test_telemetry_fields_populated(self):
        """When backend returns telemetry data, EvalResult captures it."""
        from openjarvis.evals.core.runner import EvalRunner
        from openjarvis.evals.core.types import EvalRecord

        config = RunConfig(
            benchmark="test",
            backend="jarvis-direct",
            model="test-model",
            telemetry=True,
            gpu_metrics=True,
        )

        mock_backend = MagicMock()
        mock_backend.generate_full.return_value = {
            "content": "answer",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "latency_seconds": 1.5,
            "cost_usd": 0.001,
            "energy_joules": 12.5,
            "power_watts": 250.0,
            "gpu_utilization_pct": 85.0,
            "throughput_tok_per_sec": 33.3,
            "ttft": 0.05,
            "_telemetry": {
                "energy_per_output_token_joules": 0.25,
                "throughput_per_watt": 0.133,
                "mean_itl_ms": 28.5,
            },
        }

        mock_scorer = MagicMock()
        mock_scorer.score.return_value = (True, {})

        mock_dataset = MagicMock()
        runner = EvalRunner(config, mock_dataset, mock_backend, mock_scorer)

        record = EvalRecord(
            record_id="test-1",
            problem="test",
            reference="answer",
            category="chat",
        )

        result = runner._process_one(record)

        assert result.energy_joules == 12.5
        assert result.power_watts == 250.0
        assert result.gpu_utilization_pct == 85.0
        assert result.throughput_tok_per_sec == 33.3
        assert result.ipw == pytest.approx(1.0 / 250.0)
        assert result.ipj == pytest.approx(1.0 / 12.5)
        assert result.energy_per_output_token_joules == 0.25
        assert result.throughput_per_watt == 0.133
        assert result.mean_itl_ms == 28.5
