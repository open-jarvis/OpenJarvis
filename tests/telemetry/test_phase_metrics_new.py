"""Tests for phase metrics computation."""

from __future__ import annotations

import pytest

from openjarvis.telemetry.phase_metrics import compute_phase_metrics, split_at_ttft
from openjarvis.telemetry.session import TelemetrySample, TelemetrySession


class TestComputePhaseMetrics:
    def _make_session_with_samples(self):
        """Create a session with pre-loaded samples."""
        session = TelemetrySession(monitor=None)
        # Manually push samples into the buffer
        for i in range(11):
            session._buffer.push(
                TelemetrySample(
                    timestamp_ns=i * 100_000_000,
                    gpu_power_w=100.0,
                    cpu_power_w=50.0,
                )
            )
        return session

    def test_basic_metrics(self):
        session = self._make_session_with_samples()
        result = compute_phase_metrics(session, 0, 1_000_000_000, 100)
        assert result["duration_s"] == pytest.approx(1.0, abs=1e-6)
        assert result["tokens"] == 100
        assert result["energy_j"] > 0  # trapezoidal integral

    def test_zero_tokens(self):
        session = self._make_session_with_samples()
        result = compute_phase_metrics(session, 0, 1_000_000_000, 0)
        assert result["energy_per_token_j"] == 0.0

    def test_split_at_ttft(self):
        session = self._make_session_with_samples()
        prefill, decode = split_at_ttft(
            session,
            start_ns=0,
            ttft_ns=500_000_000,  # 500ms
            end_ns=1_000_000_000,  # 1s
            input_tokens=50,
            output_tokens=100,
        )
        assert prefill["tokens"] == 50
        assert decode["tokens"] == 100
        assert prefill["duration_s"] == pytest.approx(0.5, abs=1e-6)
        assert decode["duration_s"] == pytest.approx(0.5, abs=1e-6)
