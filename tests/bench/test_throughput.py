"""Tests for the throughput benchmark."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from friday_ai.bench.throughput import ThroughputBenchmark
from friday_ai.core.registry import BenchmarkRegistry


@pytest.fixture(autouse=True)
def _register_throughput():
    """Re-register throughput benchmark after registry clear."""
    from friday_ai.bench.throughput import ensure_registered

    ensure_registered()


def _make_engine(completion_tokens=10):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "Hello world",
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": completion_tokens,
            "total_tokens": 5 + completion_tokens,
        },
    }
    return engine


class TestThroughputBenchmark:
    def test_registration(self):
        assert BenchmarkRegistry.contains("throughput")
        assert BenchmarkRegistry.get("throughput") is ThroughputBenchmark

    def test_run_with_mock(self):
        engine = _make_engine()
        b = ThroughputBenchmark()
        result = b.run(engine, "test-model", num_samples=3)
        assert result.benchmark_name == "throughput"
        assert result.model == "test-model"
        assert result.engine == "mock"
        assert result.samples == 3

    def test_metrics_keys(self):
        engine = _make_engine()
        b = ThroughputBenchmark()
        result = b.run(engine, "test-model", num_samples=3)
        assert "mean_tokens_per_second" in result.metrics
        assert "total_tokens" in result.metrics
        assert "total_time_seconds" in result.metrics

    def test_tokens_per_second_calc(self):
        engine = _make_engine(completion_tokens=10)
        b = ThroughputBenchmark()
        result = b.run(engine, "test-model", num_samples=5)
        # 5 samples * 10 tokens each = 50 total tokens
        assert result.metrics["total_tokens"] == 50.0
        assert result.metrics["mean_tokens_per_second"] > 0

    def test_sample_count(self):
        engine = _make_engine()
        b = ThroughputBenchmark()
        b.run(engine, "test-model", num_samples=7)
        assert engine.generate.call_count == 7

    def test_zero_latency_handling(self):
        """All errors should result in 0 tokens_per_second."""
        engine = _make_engine()
        engine.generate.side_effect = RuntimeError("fail")
        b = ThroughputBenchmark()
        result = b.run(engine, "test-model", num_samples=3)
        assert result.errors == 3
        assert result.metrics.get("mean_tokens_per_second", 0.0) == 0.0
