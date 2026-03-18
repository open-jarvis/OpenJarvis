"""Tests for Tier 3 — per-token timestamps, ITL percentiles, streaming telemetry."""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role, TelemetryRecord
from openjarvis.telemetry.aggregator import TelemetryAggregator
from openjarvis.telemetry.instrumented_engine import (
    InstrumentedEngine,
    _compute_itl_stats,
    _percentile,
)
from openjarvis.telemetry.store import TelemetryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_engine_with_stream(tokens=None):
    """Return a mock engine whose stream() yields the given tokens."""
    if tokens is None:
        tokens = ["Hello", " ", "world", "!"]
    engine = MagicMock()
    engine.engine_id = "mock"

    async def _stream(*args, **kwargs):
        for tok in tokens:
            yield tok

    engine.stream = _stream
    engine.generate.return_value = {
        "content": "".join(tokens),
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": len(tokens),
            "total_tokens": 5 + len(tokens),
        },
        "model": "m",
        "ttft": 0.01,
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
# Helper function tests
# ---------------------------------------------------------------------------


class TestPercentile:
    """_percentile() computes interpolated percentiles."""

    def test_simple_median(self):
        assert _percentile([1, 2, 3, 4, 5], 0.50) == pytest.approx(3.0)

    def test_p90(self):
        data = list(range(1, 101))  # 1..100
        assert _percentile(data, 0.90) == pytest.approx(90.1)

    def test_single_value(self):
        assert _percentile([42.0], 0.99) == pytest.approx(42.0)

    def test_two_values(self):
        assert _percentile([10, 20], 0.50) == pytest.approx(15.0)

    def test_unsorted_input(self):
        """Input doesn't need to be sorted."""
        assert _percentile([5, 3, 1, 4, 2], 0.50) == pytest.approx(3.0)


class TestComputeItlStats:
    """_compute_itl_stats() computes ITL summary statistics."""

    def test_empty_list(self):
        stats = _compute_itl_stats([])
        assert stats["mean"] == 0.0
        assert stats["median"] == 0.0
        assert stats["p90"] == 0.0
        assert stats["p95"] == 0.0
        assert stats["p99"] == 0.0
        assert stats["std"] == 0.0

    def test_single_value(self):
        stats = _compute_itl_stats([10.0])
        assert stats["mean"] == pytest.approx(10.0)
        assert stats["median"] == pytest.approx(10.0)
        assert stats["std"] == 0.0  # single value

    def test_known_sequence(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        stats = _compute_itl_stats(values)
        assert stats["mean"] == pytest.approx(30.0)
        assert stats["median"] == pytest.approx(30.0)
        assert stats["p90"] == pytest.approx(46.0)
        assert stats["p95"] == pytest.approx(48.0)
        assert stats["p99"] == pytest.approx(49.6)
        assert stats["std"] > 0


# ---------------------------------------------------------------------------
# Streaming tests
# ---------------------------------------------------------------------------


class TestStreamTelemetry:
    """InstrumentedEngine.stream() records telemetry with ITL."""

    def test_stream_creates_telemetry_record(self):
        bus = EventBus()
        engine = _mock_engine_with_stream(["a", "b", "c"])
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        async def run():
            tokens = []
            async for tok in ie.stream(
                [Message(role=Role.USER, content="hi")], model="m"
            ):
                tokens.append(tok)
            return tokens

        tokens = asyncio.run(run())
        assert tokens == ["a", "b", "c"]
        assert len(records) == 1
        rec = records[0]
        assert rec.is_streaming is True
        assert rec.completion_tokens == 3

    def test_stream_computes_itl(self):
        bus = EventBus()
        engine = _mock_engine_with_stream(["a", "b", "c", "d", "e"])
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        async def run():
            async for _ in ie.stream(
                [Message(role=Role.USER, content="hi")], model="m"
            ):
                pass

        asyncio.run(run())
        rec = records[0]
        # 5 tokens → 4 ITL deltas
        assert rec.mean_itl_ms >= 0
        assert rec.median_itl_ms >= 0
        assert rec.p90_itl_ms >= 0
        assert rec.p95_itl_ms >= 0
        assert rec.p99_itl_ms >= 0

    def test_stream_with_energy_monitor(self):
        bus = EventBus()
        engine = _mock_engine_with_stream(["x", "y"])
        monitor = _mock_energy_monitor(energy_joules=5.0, power_watts=100.0)
        ie = InstrumentedEngine(engine, bus, energy_monitor=monitor)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        async def run():
            async for _ in ie.stream(
                [Message(role=Role.USER, content="hi")], model="m"
            ):
                pass

        asyncio.run(run())
        rec = records[0]
        assert rec.energy_joules == 5.0
        assert rec.energy_per_output_token_joules == pytest.approx(5.0 / 2)

    def test_stream_empty_tokens(self):
        bus = EventBus()
        engine = _mock_engine_with_stream([])
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        async def run():
            async for _ in ie.stream(
                [Message(role=Role.USER, content="hi")], model="m"
            ):
                pass

        asyncio.run(run())
        rec = records[0]
        assert rec.completion_tokens == 0
        assert rec.mean_itl_ms == 0.0
        assert rec.ttft == 0.0

    def test_stream_single_token(self):
        bus = EventBus()
        engine = _mock_engine_with_stream(["only"])
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        async def run():
            async for _ in ie.stream(
                [Message(role=Role.USER, content="hi")], model="m"
            ):
                pass

        asyncio.run(run())
        rec = records[0]
        assert rec.completion_tokens == 1
        # No ITL deltas with single token
        assert rec.mean_itl_ms == 0.0
        assert rec.std_itl_ms == 0.0


class TestGenerateMeanItlApproximation:
    """generate() computes mean_itl_ms from decode_latency/completion_tokens."""

    def test_mean_itl_computed(self):
        bus = EventBus()
        engine = MagicMock()
        engine.engine_id = "mock"

        def _slow_generate(*args, **kwargs):
            time.sleep(0.05)  # ensure latency > ttft
            return {
                "content": "hi",
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                },
                "model": "m",
                "ttft": 0.01,
            }

        engine.generate.side_effect = _slow_generate
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        # decode_latency > 0 because latency > ttft
        assert rec.decode_latency_seconds > 0
        # mean_itl_ms = (decode_latency / completion_tokens) * 1000
        expected = (rec.decode_latency_seconds / 20) * 1000
        assert rec.mean_itl_ms == pytest.approx(expected)
        assert rec.is_streaming is False

    def test_no_ttft_no_itl(self):
        bus = EventBus()
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {
            "content": "hi",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "model": "m",
            "ttft": 0.0,
        }
        ie = InstrumentedEngine(engine, bus)

        records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda e: records.append(e.data["record"]),
        )

        ie.generate([Message(role=Role.USER, content="hi")], model="m")
        rec = records[0]
        assert rec.mean_itl_ms == 0.0  # no decode_latency → no ITL


class TestItlStorage:
    """ITL fields are stored and queryable."""

    def test_store_and_query_itl(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db")
        store.record(
            TelemetryRecord(
                timestamp=time.time(),
                model_id="m1",
                engine="mock",
                mean_itl_ms=15.0,
                median_itl_ms=14.0,
                p90_itl_ms=20.0,
                p95_itl_ms=25.0,
                p99_itl_ms=30.0,
                std_itl_ms=5.0,
                is_streaming=True,
            )
        )

        agg = TelemetryAggregator(tmp_path / "test.db")
        stats = agg.per_model_stats()
        assert len(stats) == 1
        assert stats[0].avg_mean_itl_ms == pytest.approx(15.0)
        assert stats[0].avg_median_itl_ms == pytest.approx(14.0)
        assert stats[0].avg_p95_itl_ms == pytest.approx(25.0)
        agg.close()
        store.close()
