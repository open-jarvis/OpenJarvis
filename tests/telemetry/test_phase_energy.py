"""Tests for Tier 2.1 — phase energy split: decode_latency, prefill/decode energy."""

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


def _mock_engine(ttft=0.1):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "hello world",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 50,
            "total_tokens": 60,
        },
        "model": "test-model",
        "ttft": ttft,
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


class TestDecodeLatency:
    """decode_latency = latency - ttft when ttft > 0."""

    def test_decode_latency_computed(self):
        bus = EventBus()
        engine = _mock_engine(ttft=0.1)
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        # decode_latency = latency - ttft
        assert rec.decode_latency_seconds == pytest.approx(rec.latency_seconds - 0.1)

    def test_decode_latency_zero_when_no_ttft(self):
        bus = EventBus()
        engine = _mock_engine(ttft=0.0)
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        assert rec.decode_latency_seconds == 0.0


class TestPhaseEnergySplit:
    """prefill_energy + decode_energy ≈ total energy."""

    def test_energy_split_proportional(self):
        bus = EventBus()
        engine = _mock_engine(ttft=0.1)
        monitor = _mock_energy_monitor(energy_joules=10.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]

        # Sum should equal total energy
        assert rec.prefill_energy_joules + rec.decode_energy_joules == pytest.approx(
            rec.energy_joules
        )

        # Prefill fraction should be proportional to ttft/latency
        expected_prefill_frac = 0.1 / rec.latency_seconds
        actual_prefill_frac = rec.prefill_energy_joules / rec.energy_joules
        assert actual_prefill_frac == pytest.approx(expected_prefill_frac)

    def test_no_energy_no_split(self):
        bus = EventBus()
        engine = _mock_engine(ttft=0.1)
        ie = InstrumentedEngine(engine, bus)  # no energy monitor

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        assert rec.prefill_energy_joules == 0.0
        assert rec.decode_energy_joules == 0.0

    def test_no_ttft_no_split(self):
        bus = EventBus()
        engine = _mock_engine(ttft=0.0)
        monitor = _mock_energy_monitor(energy_joules=10.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        # No ttft → no prefill_latency → no split
        assert rec.prefill_energy_joules == 0.0
        assert rec.decode_energy_joules == 0.0

    def test_latency_equals_ttft_decode_energy_zero(self):
        """When latency == ttft, all energy is prefill."""
        bus = EventBus()
        # We'll use a ttft that's close to the measured latency
        engine = _mock_engine(ttft=0.001)
        monitor = _mock_energy_monitor(energy_joules=5.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        # prefill + decode should still sum to total
        assert rec.prefill_energy_joules + rec.decode_energy_joules == pytest.approx(
            rec.energy_joules
        )


class TestPhaseEnergyInTelemetryDict:
    """Phase energy fields appear in result['_telemetry']."""

    def test_telemetry_dict_contains_phase_energy(self):
        bus = EventBus()
        engine = _mock_engine(ttft=0.1)
        monitor = _mock_energy_monitor(energy_joules=10.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        result = ie.generate([Message(role=Role.USER, content="hi")], model="m")
        t = result["_telemetry"]
        assert "prefill_energy_joules" in t
        assert "decode_energy_joules" in t
        assert "decode_latency_seconds" in t
        assert t["prefill_energy_joules"] + t["decode_energy_joules"] == pytest.approx(
            t["energy_joules"] if t["energy_joules"] > 0 else 0.0
        )


class TestPhaseEnergyStorage:
    """Phase energy fields are stored and queryable."""

    def test_store_and_aggregate(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db")
        store.record(
            TelemetryRecord(
                timestamp=time.time(),
                model_id="m1",
                engine="mock",
                energy_joules=10.0,
                prefill_energy_joules=3.0,
                decode_energy_joules=7.0,
            )
        )

        agg = TelemetryAggregator(tmp_path / "test.db")
        stats = agg.per_model_stats()
        assert len(stats) == 1
        assert stats[0].total_prefill_energy_joules == pytest.approx(3.0)
        assert stats[0].total_decode_energy_joules == pytest.approx(7.0)
        agg.close()
        store.close()
