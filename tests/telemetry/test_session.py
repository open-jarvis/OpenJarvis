"""Tests for TelemetrySession and ring buffer."""

from __future__ import annotations

from openjarvis.telemetry.session import (
    TelemetrySample,
    TelemetrySession,
    _PythonRingBuffer,
)


class TestPythonRingBuffer:
    def test_push_and_len(self):
        buf = _PythonRingBuffer(capacity=10)
        assert len(buf) == 0
        buf.push(TelemetrySample(timestamp_ns=100))
        assert len(buf) == 1

    def test_capacity_overflow(self):
        buf = _PythonRingBuffer(capacity=3)
        for i in range(5):
            buf.push(TelemetrySample(timestamp_ns=i * 100))
        assert len(buf) == 3

    def test_window(self):
        buf = _PythonRingBuffer(capacity=100)
        for i in range(10):
            buf.push(TelemetrySample(timestamp_ns=i * 1000))
        result = buf.window(2000, 6000)
        assert len(result) == 5  # 2000, 3000, 4000, 5000, 6000

    def test_clear(self):
        buf = _PythonRingBuffer(capacity=10)
        buf.push(TelemetrySample(timestamp_ns=1))
        buf.clear()
        assert len(buf) == 0

    def test_energy_delta_trapezoidal(self):
        """Trapezoidal integration over constant power should yield P*t."""
        buf = _PythonRingBuffer(capacity=100)
        # 100W GPU, 50W CPU for 1 second (10 samples, 100ms apart)
        for i in range(11):
            buf.push(
                TelemetrySample(
                    timestamp_ns=i * 100_000_000,  # 0ms, 100ms, ..., 1000ms
                    gpu_power_w=100.0,
                    cpu_power_w=50.0,
                )
            )
        gpu_j, cpu_j = buf.compute_energy_delta(0, 1_000_000_000)
        assert abs(gpu_j - 100.0) < 1.0  # 100W * 1s = 100J
        assert abs(cpu_j - 50.0) < 1.0  # 50W * 1s = 50J

    def test_energy_delta_insufficient_samples(self):
        buf = _PythonRingBuffer(capacity=100)
        buf.push(TelemetrySample(timestamp_ns=0, gpu_power_w=100.0))
        gpu_j, cpu_j = buf.compute_energy_delta(0, 1_000_000_000)
        assert gpu_j == 0.0
        assert cpu_j == 0.0

    def test_avg_power(self):
        buf = _PythonRingBuffer(capacity=100)
        buf.push(TelemetrySample(timestamp_ns=0, gpu_power_w=100.0, cpu_power_w=40.0))
        buf.push(
            TelemetrySample(
                timestamp_ns=500_000_000,
                gpu_power_w=200.0,
                cpu_power_w=60.0,
            )
        )
        gpu_w, cpu_w = buf.compute_avg_power(0, 1_000_000_000)
        assert gpu_w == 150.0
        assert cpu_w == 50.0


class TestTelemetrySession:
    def test_noop_session(self):
        """Session with no monitor should be a safe no-op."""
        session = TelemetrySession(monitor=None)
        with session:
            samples = session.window(0, 1_000_000_000)
            assert samples == []
            gpu_j, cpu_j = session.energy_delta(0, 1_000_000_000)
            assert gpu_j == 0.0
            assert cpu_j == 0.0

    def test_context_manager(self):
        session = TelemetrySession(monitor=None)
        with session as s:
            assert s is session

    def test_start_stop(self):
        session = TelemetrySession(monitor=None)
        session.start()
        session.stop()
