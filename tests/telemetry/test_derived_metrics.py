"""Tier 1: derived metrics — energy_per_output_token, throughput_per_watt."""

from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role, TelemetryRecord
from openjarvis.telemetry.aggregator import TelemetryAggregator
from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
from openjarvis.telemetry.store import TelemetryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_engine(completion_tokens=50):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "hello",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": completion_tokens,
            "total_tokens": 10 + completion_tokens,
        },
        "model": "test-model",
        "ttft": 0.05,
    }
    return engine


def _mock_energy_monitor(energy_joules=10.0, power_watts=200.0):
    monitor = MagicMock()
    sample = MagicMock()
    sample.energy_joules = energy_joules
    sample.mean_power_watts = power_watts
    sample.peak_power_watts = power_watts
    sample.mean_utilization_pct = 80.0
    sample.peak_utilization_pct = 95.0
    sample.mean_memory_used_gb = 16.0
    sample.peak_memory_used_gb = 20.0
    sample.mean_temperature_c = 65.0
    sample.peak_temperature_c = 72.0
    sample.duration_seconds = 0.5
    sample.num_snapshots = 10
    sample.energy_method = "hw_counter"
    sample.vendor = "nvidia"
    sample.cpu_energy_joules = 0.0
    sample.gpu_energy_joules = energy_joules
    sample.dram_energy_joules = 0.0

    @contextmanager
    def _sample():
        yield sample

    monitor.sample = _sample
    return monitor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDerivedMetricsInGenerate:
    """InstrumentedEngine.generate() computes derived metrics."""

    def test_energy_per_output_token(self):
        bus = EventBus()
        engine = _mock_engine(completion_tokens=50)
        monitor = _mock_energy_monitor(energy_joules=10.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        assert rec.energy_per_output_token_joules == pytest.approx(10.0 / 50)

    def test_throughput_per_watt(self):
        bus = EventBus()
        engine = _mock_engine(completion_tokens=100)
        monitor = _mock_energy_monitor(power_watts=250.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        # throughput_per_watt = throughput / power_watts
        expected = rec.throughput_tok_per_sec / 250.0
        assert rec.throughput_per_watt == pytest.approx(expected)

    def test_zero_completion_tokens_no_division_error(self):
        bus = EventBus()
        engine = _mock_engine(completion_tokens=0)
        monitor = _mock_energy_monitor(energy_joules=5.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        assert rec.energy_per_output_token_joules == 0.0

    def test_zero_power_no_division_error(self):
        bus = EventBus()
        engine = _mock_engine(completion_tokens=50)
        # No energy monitor -> power_watts = 0
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        assert rec.throughput_per_watt == 0.0

    def test_derived_metrics_in_telemetry_dict(self):
        bus = EventBus()
        engine = _mock_engine(completion_tokens=25)
        monitor = _mock_energy_monitor(energy_joules=5.0, power_watts=100.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        result = ie.generate([Message(role=Role.USER, content="hi")], model="m")
        t = result["_telemetry"]
        assert t["energy_per_output_token_joules"] == pytest.approx(5.0 / 25)
        assert t["throughput_per_watt"] > 0


class TestDerivedMetricsInStore:
    """Derived metrics are stored and queryable."""

    def test_store_and_query(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db")
        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id="test-model",
            engine="mock",
            completion_tokens=50,
            energy_joules=10.0,
            energy_per_output_token_joules=0.2,
            throughput_per_watt=0.5,
        )
        store.record(rec)

        agg = TelemetryAggregator(tmp_path / "test.db")
        stats = agg.per_model_stats()
        assert len(stats) == 1
        assert stats[0].avg_energy_per_output_token_joules == pytest.approx(0.2)
        assert stats[0].avg_throughput_per_watt == pytest.approx(0.5)
        agg.close()
        store.close()

    def test_summary_weighted_averages(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db")
        for i in range(3):
            store.record(
                TelemetryRecord(
                    timestamp=time.time() + i,
                    model_id="m1",
                    engine="e1",
                    energy_per_output_token_joules=0.1 * (i + 1),
                    throughput_per_watt=1.0 * (i + 1),
                )
            )
        agg = TelemetryAggregator(tmp_path / "test.db")
        summary = agg.summary()
        assert summary.avg_energy_per_output_token_joules > 0
        assert summary.avg_throughput_per_watt > 0
        agg.close()
        store.close()
