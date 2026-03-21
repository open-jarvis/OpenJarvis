"""Tests for SteadyStateConfig, SteadyStateDetector, and SteadyStateResult."""

from __future__ import annotations

from openjarvis.telemetry.steady_state import (
    SteadyStateConfig,
    SteadyStateDetector,
    SteadyStateResult,
)

# ---------------------------------------------------------------------------
# Tests: SteadyStateConfig
# ---------------------------------------------------------------------------


class TestSteadyStateConfig:
    def test_defaults(self):
        cfg = SteadyStateConfig()
        assert cfg.warmup_samples == 5
        assert cfg.window_size == 5
        assert cfg.cv_threshold == 0.05
        assert cfg.min_steady_samples == 3
        assert cfg.metric == "throughput"

    def test_custom_values(self):
        cfg = SteadyStateConfig(warmup_samples=10, cv_threshold=0.1)
        assert cfg.warmup_samples == 10
        assert cfg.cv_threshold == 0.1


# ---------------------------------------------------------------------------
# Tests: SteadyStateResult
# ---------------------------------------------------------------------------


class TestSteadyStateResult:
    def test_default_fields(self):
        r = SteadyStateResult()
        assert r.total_samples == 0
        assert r.warmup_samples == 0
        assert r.steady_state_samples == 0
        assert r.steady_state_reached is False
        assert r.warmup_throughputs == []
        assert r.warmup_energies == []
        assert r.steady_throughputs == []
        assert r.steady_energies == []


# ---------------------------------------------------------------------------
# Tests: SteadyStateDetector
# ---------------------------------------------------------------------------


class TestSteadyStateDetector:
    def test_constant_throughput_reaches_steady_state(self):
        """Constant values should produce CV=0, reaching steady state quickly."""
        cfg = SteadyStateConfig(warmup_samples=3, window_size=3, min_steady_samples=2)
        detector = SteadyStateDetector(cfg)

        reached = False
        for _ in range(20):
            reached = detector.record(throughput=100.0, energy=10.0)
            if reached:
                break
        assert reached is True
        assert detector.result.steady_state_reached is True

    def test_erratic_values_no_steady_state(self):
        """Highly variable values should not reach steady state."""
        cfg = SteadyStateConfig(
            warmup_samples=2,
            window_size=3,
            cv_threshold=0.01,
            min_steady_samples=3,
        )
        detector = SteadyStateDetector(cfg)

        # Alternate between wildly different values
        values = [10.0, 1000.0, 10.0, 1000.0, 10.0, 1000.0, 10.0, 1000.0, 10.0, 1000.0]
        for v in values:
            detector.record(throughput=v)

        assert detector.result.steady_state_reached is False

    def test_warmup_boundary(self):
        """First N samples are always warmup regardless of stability."""
        cfg = SteadyStateConfig(warmup_samples=5, window_size=3, min_steady_samples=1)
        detector = SteadyStateDetector(cfg)

        # Feed 5 constant values (all warmup)
        for _ in range(5):
            result = detector.record(throughput=100.0)
            assert result is False  # still in warmup

        r = detector.result
        assert r.warmup_samples == 5
        assert r.steady_state_samples == 0

    def test_cv_calculation_correctness(self):
        """Verify CV-based detection with known values."""
        cfg = SteadyStateConfig(
            warmup_samples=2,
            window_size=3,
            cv_threshold=0.05,
            min_steady_samples=1,
        )
        detector = SteadyStateDetector(cfg)

        # 2 warmup
        detector.record(throughput=50.0)
        detector.record(throughput=60.0)

        # Post-warmup: values with low CV (100, 101, 100 -> CV ~ 0.006)
        detector.record(throughput=100.0)
        detector.record(throughput=101.0)
        result = detector.record(throughput=100.0)

        assert result is True
        assert detector.result.steady_state_reached is True

    def test_reset_clears_state(self):
        """After reset, detector starts fresh."""
        cfg = SteadyStateConfig(warmup_samples=2, window_size=2, min_steady_samples=1)
        detector = SteadyStateDetector(cfg)

        # Get to steady state
        for _ in range(10):
            detector.record(throughput=100.0)
        assert detector.result.steady_state_reached is True

        # Reset
        detector.reset()
        r = detector.result
        assert r.total_samples == 0
        assert r.steady_state_reached is False
        assert r.warmup_throughputs == []
        assert r.steady_throughputs == []

    def test_result_partitions_warmup_and_steady(self):
        """Result should correctly partition samples into warmup and steady."""
        cfg = SteadyStateConfig(warmup_samples=3, window_size=2, min_steady_samples=1)
        detector = SteadyStateDetector(cfg)

        # 3 warmup + 4 steady
        for i in range(7):
            detector.record(throughput=float(100 + i), energy=float(10 + i))

        r = detector.result
        assert r.total_samples == 7
        assert r.warmup_samples == 3
        assert r.steady_state_samples == 4
        assert len(r.warmup_throughputs) == 3
        assert len(r.warmup_energies) == 3
        assert len(r.steady_throughputs) == 4
        assert len(r.steady_energies) == 4

    def test_default_config_when_none(self):
        """Passing None config should use defaults."""
        detector = SteadyStateDetector(None)
        assert detector._config.warmup_samples == 5
        assert detector._config.window_size == 5
