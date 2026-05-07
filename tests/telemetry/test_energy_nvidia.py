"""Tests for NvidiaEnergyMonitor -- mock pynvml (no real GPU required)."""

from __future__ import annotations

import sys
import time
import types
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from tests.telemetry.energy_test_helpers import (
    assert_available_false_when_lib_missing,
    assert_close_sets_uninitialized,
    assert_empty_sample_result,
    assert_sample_result_basics,
)

# ---------------------------------------------------------------------------
# Helpers: build a fake pynvml module
# ---------------------------------------------------------------------------


@dataclass
class _FakeUtilization:
    gpu: int = 80
    memory: int = 50


@dataclass
class _FakeMemInfo:
    total: int = 24 * 1024**3
    used: int = 12 * 1024**3
    free: int = 12 * 1024**3


def _make_fake_pynvml(device_count: int = 1, power_mw: int = 300_000):
    """Return a fake pynvml module object."""
    mod = types.ModuleType("pynvml")
    mod.nvmlInit = MagicMock()
    mod.nvmlShutdown = MagicMock()
    mod.nvmlDeviceGetCount = MagicMock(return_value=device_count)
    mod.nvmlDeviceGetHandleByIndex = MagicMock(side_effect=lambda i: f"handle-{i}")
    mod.nvmlDeviceGetName = MagicMock(return_value="NVIDIA A100-SXM")
    mod.nvmlDeviceGetPowerUsage = MagicMock(return_value=power_mw)
    mod.nvmlDeviceGetUtilizationRates = MagicMock(return_value=_FakeUtilization())
    mod.nvmlDeviceGetMemoryInfo = MagicMock(return_value=_FakeMemInfo())
    mod.nvmlDeviceGetTemperature = MagicMock(return_value=65)
    mod.nvmlDeviceGetTotalEnergyConsumption = MagicMock(return_value=5000.0)
    mod.NVML_TEMPERATURE_GPU = 0
    return mod


def _install_fake_pynvml(fake_pynvml, mod):
    """Patch energy_nvidia module to use fake pynvml."""
    mod._PYNVML_AVAILABLE = True
    mod.pynvml = fake_pynvml


# ---------------------------------------------------------------------------
# Tests: available()
# ---------------------------------------------------------------------------


class TestAvailable:
    def test_available_true_when_pynvml_works(self):
        fake_pynvml = _make_fake_pynvml(device_count=1)

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                assert mod.NvidiaEnergyMonitor.available() is True
                fake_pynvml.nvmlInit.assert_called()
                fake_pynvml.nvmlShutdown.assert_called()
            finally:
                mod._PYNVML_AVAILABLE = orig

    def test_available_false_when_pynvml_not_importable(self):
        import openjarvis.telemetry.energy_nvidia as mod

        assert_available_false_when_lib_missing(
            mod, mod.NvidiaEnergyMonitor, "_PYNVML_AVAILABLE"
        )


# ---------------------------------------------------------------------------
# Tests: hw counter probe
# ---------------------------------------------------------------------------


class TestHwCounterProbe:
    def test_probe_succeeds_on_volta_plus(self):
        """nvmlDeviceGetTotalEnergyConsumption succeeds => hw_counter_available."""
        fake_pynvml = _make_fake_pynvml(device_count=1)
        # GetTotalEnergyConsumption returns normally => Volta+
        fake_pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 1000.0

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                monitor = mod.NvidiaEnergyMonitor(poll_interval_ms=50)
                assert monitor._hw_counter_available is True
            finally:
                mod._PYNVML_AVAILABLE = orig

    def test_probe_fails_on_pre_volta(self):
        """nvmlDeviceGetTotalEnergyConsumption raises => polling fallback."""
        fake_pynvml = _make_fake_pynvml(device_count=1)
        fake_pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = RuntimeError(
            "Not supported"
        )

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                monitor = mod.NvidiaEnergyMonitor(poll_interval_ms=50)
                assert monitor._hw_counter_available is False
            finally:
                mod._PYNVML_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: energy_method()
# ---------------------------------------------------------------------------


class TestEnergyMethod:
    def test_returns_hw_counter_when_available(self):
        fake_pynvml = _make_fake_pynvml(device_count=1)

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                monitor = mod.NvidiaEnergyMonitor(poll_interval_ms=50)
                assert monitor.energy_method() == "hw_counter"
            finally:
                mod._PYNVML_AVAILABLE = orig

    def test_returns_polling_when_no_hw_counter(self):
        fake_pynvml = _make_fake_pynvml(device_count=1)
        fake_pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = RuntimeError(
            "Not supported"
        )

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                monitor = mod.NvidiaEnergyMonitor(poll_interval_ms=50)
                assert monitor.energy_method() == "polling"
            finally:
                mod._PYNVML_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: sample() with hw counters
# ---------------------------------------------------------------------------


class TestSampleHwCounters:
    def test_hw_counter_delta_math(self):
        """start=5000mJ, end=8000mJ => delta=3000mJ => 3.0 J."""
        fake_pynvml = _make_fake_pynvml(device_count=1)

        energy_readings = [5000.0, 8000.0]
        call_count = {"n": 0}

        def get_energy(handle):
            idx = min(call_count["n"], len(energy_readings) - 1)
            val = energy_readings[idx]
            call_count["n"] += 1
            return val

        fake_pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = get_energy

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                monitor = mod.NvidiaEnergyMonitor(poll_interval_ms=10)
                # _probe_hw_counter consumed one reading during __init__,
                # so reset the counter for sample()
                call_count["n"] = 0
                energy_readings_sample = [5000.0, 8000.0]

                def get_energy_sample(handle):
                    idx = min(call_count["n"], len(energy_readings_sample) - 1)
                    val = energy_readings_sample[idx]
                    call_count["n"] += 1
                    return val

                fake_pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = (
                    get_energy_sample
                )

                with monitor.sample() as result:
                    time.sleep(0.05)

                # delta = 8000 - 5000 = 3000 mJ => 3.0 J
                assert result.energy_joules == pytest.approx(3.0)
                assert result.gpu_energy_joules == pytest.approx(3.0)
                assert_sample_result_basics(
                    result, vendor="nvidia", energy_method="hw_counter"
                )
            finally:
                mod._PYNVML_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: sample() with polling fallback
# ---------------------------------------------------------------------------


class TestSamplePolling:
    def test_polling_trapezoidal_integration(self):
        """Fallback mode uses trapezoidal integration of power readings."""
        fake_pynvml = _make_fake_pynvml(device_count=1, power_mw=300_000)
        # Make hw counter probe fail => polling mode
        fake_pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = RuntimeError(
            "Not supported"
        )

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                monitor = mod.NvidiaEnergyMonitor(poll_interval_ms=10)
                assert monitor.energy_method() == "polling"

                with monitor.sample() as result:
                    time.sleep(0.15)

                # With constant 300W polling, energy should be > 0
                assert result.energy_joules > 0
                assert_sample_result_basics(
                    result, vendor="nvidia", energy_method="polling"
                )
            finally:
                mod._PYNVML_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: sample() multi-GPU
# ---------------------------------------------------------------------------


class TestSampleMultiGpu:
    def test_multi_gpu_hw_counter(self):
        """2 GPUs: energy is sum of deltas from both devices."""
        fake_pynvml = _make_fake_pynvml(device_count=2)

        # 2 devices: __init__ probe reads device 0 once.
        # Then sample() reads start (dev0, dev1), end (dev0, dev1).
        readings = iter(
            [
                1000.0,  # probe: device 0
                2000.0,  # sample start: device 0
                3000.0,  # sample start: device 1
                5000.0,  # sample end: device 0
                7000.0,  # sample end: device 1
            ]
        )

        fake_pynvml.nvmlDeviceGetTotalEnergyConsumption.side_effect = lambda h: next(
            readings
        )

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                monitor = mod.NvidiaEnergyMonitor(poll_interval_ms=10)
                assert monitor._hw_counter_available is True

                with monitor.sample() as result:
                    time.sleep(0.05)

                # dev0: 5000-2000=3000 mJ, dev1: 7000-3000=4000 mJ => 7.0 J
                assert result.energy_joules == pytest.approx(7.0)
                assert result.device_count == 2
            finally:
                mod._PYNVML_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: sample() with no devices
# ---------------------------------------------------------------------------


class TestSampleNoDevices:
    def test_no_devices_empty_result(self):
        """When no GPUs are present, sample yields empty result."""
        from openjarvis.telemetry.energy_nvidia import NvidiaEnergyMonitor

        monitor = NvidiaEnergyMonitor.__new__(NvidiaEnergyMonitor)
        monitor._poll_interval_s = 0.05
        monitor._handles = []
        monitor._device_count = 0
        monitor._device_name = ""
        monitor._initialized = False
        monitor._hw_counter_available = False

        with monitor.sample() as result:
            pass

        assert_empty_sample_result(result, vendor="nvidia")


# ---------------------------------------------------------------------------
# Tests: close()
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_calls_nvml_shutdown(self):
        fake_pynvml = _make_fake_pynvml(device_count=1)

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.energy_nvidia as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                monitor = mod.NvidiaEnergyMonitor(poll_interval_ms=50)
                assert monitor._initialized is True

                fake_pynvml.nvmlShutdown.reset_mock()
                assert_close_sets_uninitialized(monitor)
                fake_pynvml.nvmlShutdown.assert_called_once()
            finally:
                mod._PYNVML_AVAILABLE = orig
