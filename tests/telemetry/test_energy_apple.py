"""Tests for AppleEnergyMonitor.

The fake backend below mirrors the *real* ``zeus_apple_silicon`` API:
``AppleEnergyMonitor`` with ``begin_window`` / ``end_window`` /
``get_cumulative_energy``, returning an object whose rail counters are
millijoules and are individually absent on chips that do not expose them.

This matters. The previous version of this file invented a
``zeus.device.soc.apple.AppleSiliconMonitor`` class with joule-valued
``cpu_energy`` / ``ane_energy`` attributes. No such class or field has ever
existed in zeus, so the suite validated its own mock while the production
import failed on every machine and the monitor silently fell back to a
modelled estimate. Keep this stub faithful to the real library.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from tests.telemetry.energy_test_helpers import assert_sample_result_basics

# ---------------------------------------------------------------------------
# Fake zeus_apple_silicon backend
# ---------------------------------------------------------------------------


class FakeMetrics:
    """Stands in for ``zeus_apple_silicon.zeus_ext.AppleEnergyMetrics``.

    All counters are millijoules. ``None`` means the chip does not expose that
    rail, which is distinct from a zero reading.
    """

    def __init__(
        self,
        cpu_total_mj=None,
        gpu_mj=None,
        gpu_sram_mj=None,
        dram_mj=None,
        ane_mj=None,
    ):
        self.cpu_total_mj = cpu_total_mj
        self.gpu_mj = gpu_mj
        self.gpu_sram_mj = gpu_sram_mj
        self.dram_mj = dram_mj
        self.ane_mj = ane_mj
        # The real object also exposes per-core / per-cluster breakdowns that
        # cpu_total_mj already subsumes. Present here so a regression that
        # starts summing them shows up as double counting.
        self.efficiency_cores_mj = [100, 100]
        self.performance_cores_mj = [200, 200]
        self.efficiency_cluster_mj = [200]
        self.performance_cluster_mj = [400]
        self.efficiency_core_manager_mj = 50
        self.performance_core_manager_mj = 50


class FakeReader:
    """Stands in for ``zeus_apple_silicon.AppleEnergyMonitor``."""

    def __init__(self, window_metrics=None, cumulative=None):
        self._window_metrics = window_metrics or FakeMetrics()
        self._cumulative = cumulative or []
        self._cumulative_idx = 0
        self.begun: list[str] = []
        self.ended: list[str] = []

    def begin_window(self, key, restart=False):
        self.begun.append(key)

    def end_window(self, key):
        if key not in self.begun:
            raise RuntimeError("No measurement with provided key had been started.")
        self.ended.append(key)
        return self._window_metrics

    def get_cumulative_energy(self):
        if not self._cumulative:
            return FakeMetrics()
        idx = min(self._cumulative_idx, len(self._cumulative) - 1)
        self._cumulative_idx += 1
        return self._cumulative[idx]


def _monitor_with(reader, *, allow_estimates=False, chip="Apple M1 Pro", tdp=30.0):
    """Build a monitor bypassing __init__'s hardware probe."""
    from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

    m = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
    m._poll_interval_ms = 50
    m._allow_estimates = allow_estimates
    m._reader = reader
    m._chip_name = chip
    m._tdp_watts = tdp
    m._prev = None
    return m


# ---------------------------------------------------------------------------
# available()
# ---------------------------------------------------------------------------


class TestAvailable:
    def test_false_on_non_darwin(self):
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        with patch("platform.system", return_value="Linux"):
            assert AppleEnergyMonitor.available() is False
            assert AppleEnergyMonitor.estimate_available() is False

    def test_false_without_native_backend(self):
        """No IOReport backend means nothing measurable — not "available anyway".

        The old behaviour returned True on any Apple Silicon host, which is
        how a modelled estimate came to masquerade as a measurement.
        """
        import openjarvis.telemetry.energy_apple as mod

        orig = mod._NATIVE_AVAILABLE
        mod._NATIVE_AVAILABLE = False
        try:
            with (
                patch("platform.system", return_value="Darwin"),
                patch("platform.machine", return_value="arm64"),
            ):
                assert mod.AppleEnergyMonitor.available() is False
                # ...but the host is still Apple Silicon, so an explicitly
                # requested estimate remains possible.
                assert mod.AppleEnergyMonitor.estimate_available() is True
        finally:
            mod._NATIVE_AVAILABLE = orig

    def test_false_when_backend_raises(self):
        """A backend that imports but cannot construct is not available."""
        import openjarvis.telemetry.energy_apple as mod

        def _boom():
            raise RuntimeError("IOReport unavailable")

        with (
            patch("platform.system", return_value="Darwin"),
            patch("platform.machine", return_value="arm64"),
            patch.object(mod, "_NATIVE_AVAILABLE", True),
            patch.object(mod, "_AppleRailReader", _boom),
        ):
            assert mod.AppleEnergyMonitor.available() is False


# ---------------------------------------------------------------------------
# energy_method()
# ---------------------------------------------------------------------------


class TestEnergyMethod:
    def test_ioreport_when_reader_present(self):
        assert _monitor_with(FakeReader()).energy_method() == "ioreport"

    def test_tdp_estimate_without_reader(self):
        assert _monitor_with(None).energy_method() == "tdp_estimate"


# ---------------------------------------------------------------------------
# sample() — rail extraction
# ---------------------------------------------------------------------------


class TestSampleRails:
    def test_millijoules_are_converted_to_joules(self):
        reader = FakeReader(
            FakeMetrics(
                cpu_total_mj=10_000,
                gpu_mj=2_000,
                gpu_sram_mj=500,
                dram_mj=1_000,
                ane_mj=4_000,
            )
        )
        monitor = _monitor_with(reader)

        with monitor.sample() as result:
            time.sleep(0.01)

        assert reader.begun and reader.ended
        assert result.cpu_energy_joules == pytest.approx(10.0)
        # GPU is gpu_mj + gpu_sram_mj — two separate rails.
        assert result.gpu_energy_joules == pytest.approx(2.5)
        assert result.dram_energy_joules == pytest.approx(1.0)
        assert result.ane_energy_joules == pytest.approx(4.0)
        assert_sample_result_basics(result, vendor="apple", energy_method="ioreport")

    def test_soc_total_and_basis(self):
        reader = FakeReader(
            FakeMetrics(cpu_total_mj=1_000, gpu_mj=2_000, dram_mj=300, ane_mj=700)
        )
        monitor = _monitor_with(reader)

        with monitor.sample() as result:
            pass

        expected = 1.0 + 2.0 + 0.3 + 0.7
        assert result.soc_energy_joules == pytest.approx(expected)
        assert result.energy_joules == pytest.approx(expected)
        assert result.basis == "soc"

    def test_cpu_total_is_not_double_counted(self):
        """cpu_total_mj already subsumes the cluster/core breakdowns.

        Verified on an M1 Pro: efficiency_cluster + performance_cluster sums
        to cpu_total_mj. Summing both would roughly double CPU energy.
        """
        reader = FakeReader(FakeMetrics(cpu_total_mj=600))
        monitor = _monitor_with(reader)

        with monitor.sample() as result:
            pass

        assert result.cpu_energy_joules == pytest.approx(0.6)
        assert result.soc_energy_joules == pytest.approx(0.6)

    def test_absent_rail_is_not_counted_as_zero(self):
        """A chip without an ANE counter reports no ANE, and the total omits it."""
        reader = FakeReader(FakeMetrics(cpu_total_mj=2_000, gpu_mj=1_000, ane_mj=None))
        monitor = _monitor_with(reader)

        with monitor.sample() as result:
            pass

        assert result.ane_energy_joules == 0.0
        assert result.soc_energy_joules == pytest.approx(3.0)

    def test_power_is_derived_per_rail(self):
        reader = FakeReader(FakeMetrics(cpu_total_mj=1_000, gpu_mj=1_000, ane_mj=2_000))
        monitor = _monitor_with(reader)

        with monitor.sample() as result:
            time.sleep(0.05)

        assert result.duration_seconds > 0
        assert result.mean_power_watts == pytest.approx(
            result.soc_energy_joules / result.duration_seconds
        )
        assert result.ane_power_watts == pytest.approx(
            result.ane_energy_joules / result.duration_seconds
        )

    def test_body_error_survives_a_failing_end_window(self):
        """The caller's exception must not be swallowed by cleanup.

        `return` inside a `finally` discards an in-flight exception, so a
        failed end_window would have hidden whatever the body raised.
        """
        reader = FakeReader(FakeMetrics(cpu_total_mj=1_000))

        def _explode(key):
            raise RuntimeError("IOReport went away")

        reader.end_window = _explode
        monitor = _monitor_with(reader)

        with pytest.raises(ValueError, match="original"):
            with monitor.sample():
                raise ValueError("original failure")

    def test_window_closes_even_when_body_raises(self):
        reader = FakeReader(FakeMetrics(cpu_total_mj=1_000))
        monitor = _monitor_with(reader)

        with pytest.raises(ValueError):
            with monitor.sample():
                raise ValueError("boom")

        assert reader.ended == reader.begun


# ---------------------------------------------------------------------------
# sample() — no backend
# ---------------------------------------------------------------------------


class TestSampleWithoutBackend:
    def test_reports_zero_rather_than_fabricating(self):
        """Without a backend and without opt-in, no numbers are invented."""
        monitor = _monitor_with(None)

        with monitor.sample() as result:
            time.sleep(0.01)

        assert result.energy_joules == 0.0
        assert result.soc_energy_joules == 0.0
        assert result.ane_energy_joules == 0.0
        assert result.vendor == "apple"
        assert result.energy_method == "tdp_estimate"

    def test_estimate_is_produced_only_when_opted_in(self):
        monitor = _monitor_with(None, allow_estimates=True, tdp=30.0)

        with monitor.sample() as result:
            time.sleep(0.05)

        assert result.energy_joules > 0.0
        assert result.mean_power_watts == pytest.approx(30.0 * 0.60, rel=1e-6)
        assert result.energy_method == "tdp_estimate"


# ---------------------------------------------------------------------------
# snapshot()
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_reports_cumulative_energy_and_derived_power(self):
        """Energy fields are cumulative counters; power comes from the delta.

        The eval runners difference these across a window
        (``_compute_energy_delta`` is last-minus-first), so a snapshot must
        carry the running counter, not a per-interval delta.
        """
        reader = FakeReader(
            cumulative=[
                FakeMetrics(cpu_total_mj=1_000, gpu_mj=500, ane_mj=100),
                FakeMetrics(cpu_total_mj=3_000, gpu_mj=700, ane_mj=900),
            ]
        )
        monitor = _monitor_with(reader)

        first = monitor.snapshot()
        assert first.cpu_energy_joules == pytest.approx(1.0)
        # No previous reading to difference against yet.
        assert first.soc_power_watts == 0.0

        time.sleep(0.05)
        second = monitor.snapshot()
        assert second.cpu_energy_joules == pytest.approx(3.0)
        assert second.soc_power_watts > 0.0
        assert second.ane_power_watts > 0.0
        assert second.basis == "soc"

    def test_counter_reset_reports_no_power_rather_than_negative(self):
        reader = FakeReader(
            cumulative=[
                FakeMetrics(cpu_total_mj=5_000),
                FakeMetrics(cpu_total_mj=10),
            ]
        )
        monitor = _monitor_with(reader)

        monitor.snapshot()
        second = monitor.snapshot()

        assert second.cpu_power_watts == 0.0

    def test_empty_without_backend(self):
        result = _monitor_with(None).snapshot()

        assert result.energy_joules == 0.0
        assert result.vendor == "apple"


# ---------------------------------------------------------------------------
# On-hardware smoke test
# ---------------------------------------------------------------------------


@pytest.mark.apple
class TestOnRealHardware:
    def test_measures_more_energy_under_load_than_idle(self):
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        if not AppleEnergyMonitor.available():
            pytest.skip("zeus-apple-silicon not installed")

        monitor = AppleEnergyMonitor()

        with monitor.sample() as idle:
            time.sleep(0.5)

        with monitor.sample() as busy:
            t = time.time()
            x = 0
            while time.time() - t < 0.5:
                x = (x * 31 + 7) % 1000003

        assert busy.soc_energy_joules > 0
        # The whole point of measuring rather than modelling: load must move
        # the number. The old wall-clock × TDP estimate could not tell these
        # two windows apart.
        assert busy.mean_power_watts > idle.mean_power_watts
        monitor.close()
