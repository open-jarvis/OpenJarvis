"""Tests for the latency benchmark."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openjarvis.bench.latency import LatencyBenchmark
from openjarvis.core.registry import BenchmarkRegistry


@pytest.fixture(autouse=True)
def _register_latency():
    """Re-register latency benchmark after registry clear."""
    from openjarvis.bench.latency import ensure_registered

    ensure_registered()


def _make_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "Hello",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    return engine


class TestLatencyBenchmark:
    def test_registration(self):
        assert BenchmarkRegistry.contains("latency")
        assert BenchmarkRegistry.get("latency") is LatencyBenchmark

    def test_name(self):
        b = LatencyBenchmark()
        assert b.name == "latency"

    def test_description(self):
        b = LatencyBenchmark()
        assert "latency" in b.description.lower()

    def test_run_with_mock_engine(self):
        engine = _make_engine()
        b = LatencyBenchmark()
        result = b.run(engine, "test-model", num_samples=3)
        assert result.benchmark_name == "latency"
        assert result.model == "test-model"
        assert result.engine == "mock"
        assert result.samples == 3
        assert result.errors == 0

    def test_metrics_keys(self):
        engine = _make_engine()
        b = LatencyBenchmark()
        result = b.run(engine, "test-model", num_samples=3)
        expected_keys = {
            "mean_latency",
            "p50_latency",
            "p95_latency",
            "min_latency",
            "max_latency",
            "std_latency",
        }
        assert set(result.metrics.keys()) == expected_keys

    def test_sample_count(self):
        engine = _make_engine()
        b = LatencyBenchmark()
        b.run(engine, "test-model", num_samples=5)
        assert engine.generate.call_count == 5

    def test_run_with_errors(self):
        engine = _make_engine()
        engine.generate.side_effect = RuntimeError("fail")
        b = LatencyBenchmark()
        result = b.run(engine, "test-model", num_samples=3)
        assert result.errors == 3
        assert result.metrics == {}

    def test_ensure_registered(self):
        from openjarvis.bench.latency import ensure_registered

        ensure_registered()  # should not raise
        assert BenchmarkRegistry.contains("latency")
