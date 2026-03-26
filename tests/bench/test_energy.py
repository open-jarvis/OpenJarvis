"""Tests for the energy benchmark."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from openjarvis.bench.energy import EnergyBenchmark
from openjarvis.core.registry import BenchmarkRegistry
from openjarvis.telemetry.energy_monitor import EnergySample


@pytest.fixture(autouse=True)
def _register_energy():
    """Re-register energy benchmark after registry clear."""
    from openjarvis.bench.energy import ensure_registered

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


class TestEnergyBenchmark:
    def test_registration(self):
        assert BenchmarkRegistry.contains("energy")
        assert BenchmarkRegistry.get("energy") is EnergyBenchmark

    def test_name_and_description(self):
        b = EnergyBenchmark()
        assert b.name == "energy"
        assert "energy" in b.description.lower()

    def test_run_without_energy_monitor(self):
        """Running without an energy monitor should still return metrics."""
        engine = _make_engine()
        b = EnergyBenchmark()
        result = b.run(engine, "test-model", num_samples=3, warmup_samples=0)

        assert result.benchmark_name == "energy"
        assert result.model == "test-model"
        assert result.engine == "mock"
        assert result.samples == 3
        assert result.errors == 0
        assert "mean_tokens_per_second" in result.metrics
        assert "total_energy_joules" in result.metrics
        assert result.metrics["total_energy_joules"] == 0.0
        assert result.energy_method == ""

    def test_run_with_mock_energy_monitor(self):
        """Running with a mock energy monitor should populate energy fields."""
        engine = _make_engine(completion_tokens=10)

        # Create a mock energy monitor with a sample() context manager
        monitor = MagicMock()
        monitor.energy_method.return_value = "polling"

        sample = EnergySample(energy_joules=5.0, mean_power_watts=100.0)

        @contextmanager
        def mock_sample():
            yield sample

        monitor.sample = mock_sample

        b = EnergyBenchmark()
        result = b.run(
            engine,
            "test-model",
            num_samples=3,
            warmup_samples=0,
            energy_monitor=monitor,
        )

        assert result.benchmark_name == "energy"
        assert result.total_energy_joules == 15.0
        assert result.energy_method == "polling"
        assert result.energy_per_token_joules > 0.0

    def test_warmup_samples_excluded(self):
        """Warmup samples should not be included in measurement metrics."""
        engine = _make_engine()
        b = EnergyBenchmark()

        result = b.run(engine, "test-model", num_samples=3, warmup_samples=2)

        assert result.warmup_samples == 2
        assert result.samples == 3
        # warmup (2) + measurement (3) = 5 total calls
        assert engine.generate.call_count == 5

    def test_run_with_errors(self):
        """All errors should result in zero metrics."""
        engine = _make_engine()
        engine.generate.side_effect = RuntimeError("fail")
        b = EnergyBenchmark()
        result = b.run(engine, "test-model", num_samples=3, warmup_samples=0)

        assert result.errors == 3
        assert result.metrics.get("mean_tokens_per_second", 0.0) == 0.0
        assert result.metrics.get("total_energy_joules", 0.0) == 0.0

    def test_ensure_registered(self):
        from openjarvis.bench.energy import ensure_registered

        ensure_registered()  # should not raise
        assert BenchmarkRegistry.contains("energy")
