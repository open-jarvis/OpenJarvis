"""Tests for batch-level energy accounting."""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator

import pytest

from friday_ai.telemetry.batch import BatchMetrics, EnergyBatch

# ---------------------------------------------------------------------------
# BatchMetrics defaults
# ---------------------------------------------------------------------------


class TestBatchMetricsDefaults:
    def test_all_defaults(self) -> None:
        m = BatchMetrics()
        assert m.batch_id == ""
        assert m.total_requests == 0
        assert m.total_tokens == 0
        assert m.total_energy_joules == 0.0
        assert m.energy_per_token_joules == 0.0
        assert m.energy_per_request_joules == 0.0
        assert m.mean_power_watts == 0.0
        assert m.mean_throughput_tok_per_sec == 0.0
        assert m.per_request_energy == []

    def test_custom_values(self) -> None:
        m = BatchMetrics(
            batch_id="abc",
            total_requests=5,
            total_tokens=100,
            total_energy_joules=10.0,
            energy_per_token_joules=0.1,
            energy_per_request_joules=2.0,
            mean_power_watts=50.0,
            mean_throughput_tok_per_sec=200.0,
            per_request_energy=[1.0, 2.0, 3.0, 2.5, 1.5],
        )
        assert m.batch_id == "abc"
        assert m.total_requests == 5
        assert m.per_request_energy == [1.0, 2.0, 3.0, 2.5, 1.5]


# ---------------------------------------------------------------------------
# Batch ID generation
# ---------------------------------------------------------------------------


class TestBatchIdGeneration:
    def test_auto_generated_uuid(self) -> None:
        batch = EnergyBatch()
        # UUID4 format: 8-4-4-4-12 hex digits
        uuid4_re = (
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}"
            r"-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
        assert re.match(uuid4_re, batch.batch_id)

    def test_custom_batch_id(self) -> None:
        batch = EnergyBatch(batch_id="my-batch-42")
        assert batch.batch_id == "my-batch-42"

    def test_unique_ids(self) -> None:
        ids = {EnergyBatch().batch_id for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# EnergyBatch without monitor
# ---------------------------------------------------------------------------


class TestEnergyBatchNoMonitor:
    def test_record_request_accumulation(self) -> None:
        batch = EnergyBatch()
        with batch.sample() as ctx:
            ctx.record_request(tokens=50)
            ctx.record_request(tokens=30)
            ctx.record_request(tokens=20)

        assert batch.metrics is not None
        assert batch.metrics.total_requests == 3
        assert batch.metrics.total_tokens == 100

    def test_energy_stays_zero_without_monitor(self) -> None:
        batch = EnergyBatch()
        with batch.sample() as ctx:
            ctx.record_request(tokens=50)

        assert batch.metrics is not None
        assert batch.metrics.total_energy_joules == 0.0
        assert batch.metrics.energy_per_token_joules == 0.0
        assert batch.metrics.mean_power_watts == 0.0

    def test_per_request_energy_from_record(self) -> None:
        """When no monitor, per-request energy comes from record_request calls."""
        batch = EnergyBatch()
        with batch.sample() as ctx:
            ctx.record_request(tokens=50, energy_joules=1.0)
            ctx.record_request(tokens=30, energy_joules=2.0)

        assert batch.metrics is not None
        assert batch.metrics.per_request_energy == [1.0, 2.0]
        assert batch.metrics.total_energy_joules == 3.0

    def test_metrics_computed_on_exit(self) -> None:
        batch = EnergyBatch()
        assert batch.metrics is None  # Before sample()
        with batch.sample() as ctx:
            ctx.record_request(tokens=100)
        assert batch.metrics is not None

    def test_no_requests_yields_zero_metrics(self) -> None:
        batch = EnergyBatch()
        with batch.sample() as _ctx:
            pass  # No requests recorded

        m = batch.metrics
        assert m is not None
        assert m.total_requests == 0
        assert m.total_tokens == 0
        assert m.energy_per_token_joules == 0.0
        assert m.energy_per_request_joules == 0.0

    def test_throughput_computed(self) -> None:
        batch = EnergyBatch()
        with batch.sample() as ctx:
            ctx.record_request(tokens=1000)

        assert batch.metrics is not None
        assert batch.metrics.mean_throughput_tok_per_sec > 0


# ---------------------------------------------------------------------------
# EnergyBatch with mock monitor
# ---------------------------------------------------------------------------


@dataclass
class _FakeEnergySample:
    energy_joules: float = 0.0
    mean_power_watts: float = 0.0


class _FakeMonitor:
    """Minimal mock that mimics EnergyMonitor.sample() context manager."""

    def __init__(self, energy_joules: float = 10.0, mean_power_watts: float = 200.0):
        self._energy = energy_joules
        self._power = mean_power_watts

    @contextmanager
    def sample(self) -> Generator[_FakeEnergySample, None, None]:
        s = _FakeEnergySample()
        yield s
        s.energy_joules = self._energy
        s.mean_power_watts = self._power


class TestEnergyBatchWithMonitor:
    def test_energy_from_monitor(self) -> None:
        monitor = _FakeMonitor(energy_joules=10.0, mean_power_watts=200.0)
        batch = EnergyBatch(energy_monitor=monitor)
        with batch.sample() as ctx:
            ctx.record_request(tokens=100)

        m = batch.metrics
        assert m is not None
        assert m.total_energy_joules == pytest.approx(10.0)
        assert m.mean_power_watts == pytest.approx(200.0)

    def test_energy_per_token_with_monitor(self) -> None:
        monitor = _FakeMonitor(energy_joules=20.0)
        batch = EnergyBatch(energy_monitor=monitor)
        with batch.sample() as ctx:
            ctx.record_request(tokens=100)
            ctx.record_request(tokens=100)

        m = batch.metrics
        assert m is not None
        assert m.total_tokens == 200
        assert m.energy_per_token_joules == pytest.approx(20.0 / 200.0)

    def test_energy_per_request_with_monitor(self) -> None:
        monitor = _FakeMonitor(energy_joules=15.0)
        batch = EnergyBatch(energy_monitor=monitor)
        with batch.sample() as ctx:
            ctx.record_request(tokens=50)
            ctx.record_request(tokens=50)
            ctx.record_request(tokens=50)

        m = batch.metrics
        assert m is not None
        assert m.total_requests == 3
        assert m.energy_per_request_joules == pytest.approx(15.0 / 3.0)

    def test_batch_id_in_metrics(self) -> None:
        batch = EnergyBatch(batch_id="test-batch-99")
        with batch.sample() as ctx:
            ctx.record_request(tokens=10)

        assert batch.metrics is not None
        assert batch.metrics.batch_id == "test-batch-99"


# ---------------------------------------------------------------------------
# Energy per token calculation
# ---------------------------------------------------------------------------


class TestEnergyPerToken:
    def test_basic_division(self) -> None:
        monitor = _FakeMonitor(energy_joules=50.0)
        batch = EnergyBatch(energy_monitor=monitor)
        with batch.sample() as ctx:
            ctx.record_request(tokens=500)

        assert batch.metrics is not None
        assert batch.metrics.energy_per_token_joules == pytest.approx(50.0 / 500.0)

    def test_zero_tokens_yields_zero(self) -> None:
        monitor = _FakeMonitor(energy_joules=10.0)
        batch = EnergyBatch(energy_monitor=monitor)
        with batch.sample() as _ctx:
            pass  # No requests

        assert batch.metrics is not None
        assert batch.metrics.energy_per_token_joules == 0.0

    def test_many_small_requests(self) -> None:
        monitor = _FakeMonitor(energy_joules=1.0)
        batch = EnergyBatch(energy_monitor=monitor)
        with batch.sample() as ctx:
            for _ in range(100):
                ctx.record_request(tokens=10)

        m = batch.metrics
        assert m is not None
        assert m.total_tokens == 1000
        assert m.total_requests == 100
        assert m.energy_per_token_joules == pytest.approx(1.0 / 1000.0)


# ---------------------------------------------------------------------------
# Per-request energy list tracking
# ---------------------------------------------------------------------------


class TestPerRequestEnergy:
    def test_tracks_each_request(self) -> None:
        batch = EnergyBatch()
        with batch.sample() as ctx:
            ctx.record_request(tokens=10, energy_joules=0.5)
            ctx.record_request(tokens=20, energy_joules=1.0)
            ctx.record_request(tokens=30, energy_joules=1.5)

        m = batch.metrics
        assert m is not None
        assert m.per_request_energy == [0.5, 1.0, 1.5]
        assert len(m.per_request_energy) == 3

    def test_empty_when_no_requests(self) -> None:
        batch = EnergyBatch()
        with batch.sample() as _ctx:
            pass

        assert batch.metrics is not None
        assert batch.metrics.per_request_energy == []

    def test_zeros_when_no_per_request_energy(self) -> None:
        batch = EnergyBatch()
        with batch.sample() as ctx:
            ctx.record_request(tokens=10)
            ctx.record_request(tokens=20)

        m = batch.metrics
        assert m is not None
        assert m.per_request_energy == [0.0, 0.0]
