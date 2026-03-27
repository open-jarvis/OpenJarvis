"""Tests for core data types."""

from __future__ import annotations

from openjarvis.evals.core.types import (
    BenchmarkConfig,
    DefaultsConfig,
    EvalRecord,
    EvalResult,
    EvalSuiteConfig,
    ExecutionConfig,
    JudgeConfig,
    MetaConfig,
    MetricStats,
    ModelConfig,
    RunConfig,
    RunSummary,
)


class TestEvalRecord:
    def test_creation(self):
        r = EvalRecord(
            record_id="r1",
            problem="What?",
            reference="42",
            category="reasoning",
        )
        assert r.record_id == "r1"
        assert r.problem == "What?"
        assert r.reference == "42"
        assert r.category == "reasoning"
        assert r.subject == ""
        assert r.metadata == {}

    def test_with_subject_and_metadata(self):
        r = EvalRecord(
            record_id="r2",
            problem="Q",
            reference="A",
            category="chat",
            subject="greet",
            metadata={"key": "val"},
        )
        assert r.subject == "greet"
        assert r.metadata == {"key": "val"}


class TestEvalResult:
    def test_defaults(self):
        r = EvalResult(record_id="r1", model_answer="42")
        assert r.is_correct is None
        assert r.score is None
        assert r.latency_seconds == 0.0
        assert r.prompt_tokens == 0
        assert r.completion_tokens == 0
        assert r.cost_usd == 0.0
        assert r.error is None
        assert r.scoring_metadata == {}
        assert r.ttft == 0.0
        assert r.energy_joules == 0.0
        assert r.power_watts == 0.0
        assert r.gpu_utilization_pct == 0.0
        assert r.throughput_tok_per_sec == 0.0
        assert r.mfu_pct == 0.0
        assert r.mbu_pct == 0.0
        assert r.ipw == 0.0
        assert r.ipj == 0.0

    def test_full(self):
        r = EvalResult(
            record_id="r1",
            model_answer="42",
            is_correct=True,
            score=1.0,
            latency_seconds=1.5,
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
            scoring_metadata={"match": "exact"},
        )
        assert r.is_correct is True
        assert r.score == 1.0
        assert r.cost_usd == 0.01

    def test_telemetry_fields(self):
        r = EvalResult(
            record_id="r1",
            model_answer="42",
            energy_joules=100.5,
            power_watts=250.0,
            gpu_utilization_pct=45.0,
            throughput_tok_per_sec=38.5,
            mfu_pct=0.018,
            mbu_pct=27.5,
            ipw=0.004,
            ipj=0.0001,
        )
        assert r.energy_joules == 100.5
        assert r.power_watts == 250.0
        assert r.gpu_utilization_pct == 45.0
        assert r.throughput_tok_per_sec == 38.5
        assert r.mfu_pct == 0.018
        assert r.mbu_pct == 27.5
        assert r.ipw == 0.004
        assert r.ipj == 0.0001


class TestRunConfig:
    def test_defaults(self):
        c = RunConfig(benchmark="supergpqa", backend="jarvis-direct", model="qwen3:8b")
        assert c.max_samples is None
        assert c.max_workers == 4
        assert c.temperature == 0.0
        assert c.max_tokens == 2048
        assert c.judge_model == "gpt-5-mini-2025-08-07"
        assert c.seed == 42
        assert c.tools == []
        assert c.telemetry is False
        assert c.gpu_metrics is False
        assert c.metadata == {}

    def test_with_agent(self):
        c = RunConfig(
            benchmark="gaia",
            backend="jarvis-agent",
            model="gpt-4o",
            engine_key="cloud",
            agent_name="orchestrator",
            tools=["calculator", "think"],
        )
        assert c.agent_name == "orchestrator"
        assert c.tools == ["calculator", "think"]

    def test_with_metadata(self):
        meta = {"param_count_b": 30.0, "active_params_b": 3.0, "num_gpus": 4}
        c = RunConfig(
            benchmark="supergpqa",
            backend="jarvis-direct",
            model="m",
            metadata=meta,
        )
        assert c.metadata["param_count_b"] == 30.0
        assert c.metadata["active_params_b"] == 3.0
        assert c.metadata["num_gpus"] == 4

    def test_metadata_independent(self):
        """Each RunConfig should have its own metadata dict."""
        c1 = RunConfig(benchmark="a", backend="b", model="m")
        c2 = RunConfig(benchmark="a", backend="b", model="m")
        c1.metadata["key"] = "val"
        assert c2.metadata == {}


class TestMetricStats:
    def test_defaults(self):
        ms = MetricStats()
        assert ms.mean == 0.0
        assert ms.median == 0.0
        assert ms.min == 0.0
        assert ms.max == 0.0
        assert ms.std == 0.0

    def test_with_values(self):
        ms = MetricStats(mean=0.5, median=0.4, min=0.1, max=0.9, std=0.2)
        assert ms.mean == 0.5
        assert ms.median == 0.4
        assert ms.min == 0.1
        assert ms.max == 0.9
        assert ms.std == 0.2


class TestRunSummary:
    def test_creation(self):
        s = RunSummary(
            benchmark="supergpqa",
            category="reasoning",
            backend="jarvis-direct",
            model="qwen3:8b",
            total_samples=100,
            scored_samples=95,
            correct=47,
            accuracy=0.495,
            errors=5,
            mean_latency_seconds=2.1,
            total_cost_usd=0.0,
            per_subject={"math": {"accuracy": 0.5}},
        )
        assert s.accuracy == 0.495
        assert s.per_subject["math"]["accuracy"] == 0.5
        assert s.started_at == 0.0

    def test_metric_stats_fields(self):
        stats = MetricStats(mean=0.5, median=0.4, min=0.1, max=0.9, std=0.2)
        s = RunSummary(
            benchmark="test",
            category="reasoning",
            backend="jarvis-direct",
            model="m",
            total_samples=10,
            scored_samples=10,
            correct=5,
            accuracy=0.5,
            errors=0,
            mean_latency_seconds=1.0,
            total_cost_usd=0.0,
            accuracy_stats=stats,
            energy_stats=stats,
            mfu_stats=stats,
            mbu_stats=stats,
            ipw_stats=stats,
            ipj_stats=stats,
            total_energy_joules=1000.0,
        )
        assert s.accuracy_stats is not None
        assert s.accuracy_stats.mean == 0.5
        assert s.energy_stats is not None
        assert s.mfu_stats is not None
        assert s.mbu_stats is not None
        assert s.ipw_stats is not None
        assert s.ipj_stats is not None
        assert s.total_energy_joules == 1000.0

    def test_metric_stats_defaults_none(self):
        s = RunSummary(
            benchmark="test",
            category="test",
            backend="mock",
            model="m",
            total_samples=0,
            scored_samples=0,
            correct=0,
            accuracy=0.0,
            errors=0,
            mean_latency_seconds=0.0,
            total_cost_usd=0.0,
        )
        assert s.accuracy_stats is None
        assert s.energy_stats is None
        assert s.mfu_stats is None
        assert s.ipw_stats is None
        assert s.total_energy_joules == 0.0


# ---------------------------------------------------------------------------
# Eval suite config dataclasses
# ---------------------------------------------------------------------------


class TestEvalResultTraceFields:
    def test_trace_fields_exist(self):
        r = EvalResult(record_id="test", model_answer="hi")
        assert r.trace_steps == 0
        assert r.trace_energy_joules == 0.0

    def test_trace_fields_set(self):
        r = EvalResult(
            record_id="test",
            model_answer="hi",
            trace_steps=5,
            trace_energy_joules=100.0,
        )
        assert r.trace_steps == 5
        assert r.trace_energy_joules == 100.0


class TestRunSummaryTraceFields:
    def test_trace_aggregate_fields(self):
        s = RunSummary(
            benchmark="test",
            category="test",
            backend="test",
            model="test",
            total_samples=1,
            scored_samples=1,
            correct=1,
            accuracy=1.0,
            errors=0,
            mean_latency_seconds=1.0,
            total_cost_usd=0.0,
        )
        assert s.avg_power_watts == 0.0
        assert s.trace_step_type_stats == {}
        assert s.total_input_tokens == 0
        assert s.total_output_tokens == 0


class TestMetaConfig:
    def test_defaults(self):
        m = MetaConfig()
        assert m.name == ""
        assert m.description == ""

    def test_with_values(self):
        m = MetaConfig(name="suite-1", description="First suite")
        assert m.name == "suite-1"
        assert m.description == "First suite"


class TestDefaultsConfig:
    def test_defaults(self):
        d = DefaultsConfig()
        assert d.temperature == 0.0
        assert d.max_tokens == 2048

    def test_with_values(self):
        d = DefaultsConfig(temperature=0.7, max_tokens=4096)
        assert d.temperature == 0.7
        assert d.max_tokens == 4096


class TestJudgeConfig:
    def test_defaults(self):
        j = JudgeConfig()
        assert j.model == "gpt-5-mini-2025-08-07"
        assert j.provider is None
        assert j.temperature == 0.0
        assert j.max_tokens == 1024

    def test_with_values(self):
        j = JudgeConfig(model="claude", provider="anthropic", temperature=0.1)
        assert j.model == "claude"
        assert j.provider == "anthropic"
        assert j.temperature == 0.1


class TestExecutionConfig:
    def test_defaults(self):
        e = ExecutionConfig()
        assert e.max_workers == 4
        assert e.output_dir == "results/"
        assert e.seed == 42

    def test_with_values(self):
        e = ExecutionConfig(max_workers=16, output_dir="out/", seed=99)
        assert e.max_workers == 16
        assert e.output_dir == "out/"
        assert e.seed == 99


class TestModelConfig:
    def test_required_name(self):
        m = ModelConfig(name="qwen3:8b")
        assert m.name == "qwen3:8b"
        assert m.engine is None
        assert m.provider is None
        assert m.temperature is None
        assert m.max_tokens is None
        assert m.param_count_b == 0.0
        assert m.active_params_b is None
        assert m.gpu_peak_tflops == 0.0
        assert m.gpu_peak_bandwidth_gb_s == 0.0
        assert m.num_gpus == 1

    def test_with_overrides(self):
        m = ModelConfig(
            name="gpt-4o",
            engine="cloud",
            provider="openai",
            temperature=0.5,
            max_tokens=4096,
        )
        assert m.engine == "cloud"
        assert m.provider == "openai"
        assert m.temperature == 0.5
        assert m.max_tokens == 4096

    def test_hardware_params(self):
        m = ModelConfig(
            name="GLM-4.7-Flash",
            engine="vllm",
            param_count_b=30.0,
            active_params_b=3.0,
            gpu_peak_tflops=312.0,
            gpu_peak_bandwidth_gb_s=2039.0,
            num_gpus=4,
        )
        assert m.param_count_b == 30.0
        assert m.active_params_b == 3.0
        assert m.gpu_peak_tflops == 312.0
        assert m.gpu_peak_bandwidth_gb_s == 2039.0
        assert m.num_gpus == 4


class TestBenchmarkConfig:
    def test_defaults(self):
        b = BenchmarkConfig(name="supergpqa")
        assert b.name == "supergpqa"
        assert b.backend == "jarvis-direct"
        assert b.max_samples is None
        assert b.split is None
        assert b.agent is None
        assert b.tools == []
        assert b.judge_model is None
        assert b.temperature is None
        assert b.max_tokens is None

    def test_with_overrides(self):
        b = BenchmarkConfig(
            name="gaia",
            backend="jarvis-agent",
            max_samples=50,
            split="test",
            agent="orchestrator",
            tools=["calc", "think"],
            judge_model="custom-judge",
            temperature=0.3,
            max_tokens=1024,
        )
        assert b.backend == "jarvis-agent"
        assert b.max_samples == 50
        assert b.split == "test"
        assert b.agent == "orchestrator"
        assert b.tools == ["calc", "think"]
        assert b.judge_model == "custom-judge"
        assert b.temperature == 0.3

    def test_tools_list_independent(self):
        """Each BenchmarkConfig instance should have its own tools list."""
        b1 = BenchmarkConfig(name="a")
        b2 = BenchmarkConfig(name="b")
        b1.tools.append("calc")
        assert b2.tools == []


class TestEvalSuiteConfig:
    def test_defaults(self):
        s = EvalSuiteConfig()
        assert isinstance(s.meta, MetaConfig)
        assert isinstance(s.defaults, DefaultsConfig)
        assert isinstance(s.judge, JudgeConfig)
        assert isinstance(s.run, ExecutionConfig)
        assert s.models == []
        assert s.benchmarks == []

    def test_with_entries(self):
        s = EvalSuiteConfig(
            meta=MetaConfig(name="test"),
            models=[ModelConfig(name="m1"), ModelConfig(name="m2")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        assert s.meta.name == "test"
        assert len(s.models) == 2
        assert len(s.benchmarks) == 1
