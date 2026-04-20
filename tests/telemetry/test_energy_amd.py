"""Tests for AmdEnergyMonitor -- mock amdsmi (no real GPU required)."""

from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock, patch

import pytest

from tests.telemetry.energy_test_helpers import (
    assert_available_false_when_lib_missing,
    assert_close_sets_uninitialized,
    assert_empty_sample_result,
    assert_sample_result_basics,
)

# ---------------------------------------------------------------------------
# Helpers: build a fake amdsmi module
# ---------------------------------------------------------------------------


def _make_fake_amdsmi(device_count: int = 1):
    """Return a fake amdsmi module object."""
    mod = types.ModuleType("amdsmi")
    mod.amdsmi_init = MagicMock()
    mod.amdsmi_shut_down = MagicMock()
    handles = [f"amd-handle-{i}" for i in range(device_count)]
    mod.amdsmi_get_processor_handles = MagicMock(return_value=handles)
    mod.amdsmi_get_gpu_asic_info = MagicMock(
        return_value={"market_name": "AMD Instinct MI300X"}
    )
    mod.amdsmi_get_energy_count = MagicMock(
        return_value={"energy_accumulator": 1000.0, "counter_resolution": 15.3}
    )
    return mod


# ---------------------------------------------------------------------------
# Tests: available()
# ---------------------------------------------------------------------------


class TestAvailable:
    def test_available_true_when_amdsmi_works(self):
        fake_amdsmi = _make_fake_amdsmi(device_count=1)

        with patch.dict(sys.modules, {"amdsmi": fake_amdsmi}):
            import openjarvis.telemetry.energy_amd as mod

            orig = mod._AMDSMI_AVAILABLE
            mod._AMDSMI_AVAILABLE = True
            mod.amdsmi = fake_amdsmi
            try:
                assert mod.AmdEnergyMonitor.available() is True
                fake_amdsmi.amdsmi_init.assert_called()
                fake_amdsmi.amdsmi_shut_down.assert_called()
            finally:
                mod._AMDSMI_AVAILABLE = orig

    def test_available_false_when_amdsmi_not_importable(self):
        import openjarvis.telemetry.energy_amd as mod

        assert_available_false_when_lib_missing(
            mod, mod.AmdEnergyMonitor, "_AMDSMI_AVAILABLE"
        )


# ---------------------------------------------------------------------------
# Tests: energy_method()
# ---------------------------------------------------------------------------


class TestEnergyMethod:
    def test_returns_hw_counter(self):
        fake_amdsmi = _make_fake_amdsmi(device_count=1)

        with patch.dict(sys.modules, {"amdsmi": fake_amdsmi}):
            import openjarvis.telemetry.energy_amd as mod

            orig = mod._AMDSMI_AVAILABLE
            mod._AMDSMI_AVAILABLE = True
            mod.amdsmi = fake_amdsmi
            try:
                monitor = mod.AmdEnergyMonitor(poll_interval_ms=50)
                assert monitor.energy_method() == "hw_counter"
            finally:
                mod._AMDSMI_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: sample() counter delta math
# ---------------------------------------------------------------------------


class TestSampleCounterDelta:
    def test_counter_delta_microjoules_to_joules(self):
        """acc_start=1000, acc_end=2000, resolution=15.3 =>
        delta=1000 * 15.3 = 15300 uJ => 0.0153 J."""
        fake_amdsmi = _make_fake_amdsmi(device_count=1)

        call_count = {"n": 0}
        readings = [
            {"energy_accumulator": 1000.0, "counter_resolution": 15.3},
            {"energy_accumulator": 2000.0, "counter_resolution": 15.3},
        ]

        def get_energy(handle):
            idx = min(call_count["n"], len(readings) - 1)
            val = readings[idx]
            call_count["n"] += 1
            return val

        fake_amdsmi.amdsmi_get_energy_count.side_effect = get_energy

        with patch.dict(sys.modules, {"amdsmi": fake_amdsmi}):
            import openjarvis.telemetry.energy_amd as mod

            orig = mod._AMDSMI_AVAILABLE
            mod._AMDSMI_AVAILABLE = True
            mod.amdsmi = fake_amdsmi
            try:
                monitor = mod.AmdEnergyMonitor(poll_interval_ms=50)
                # Reset for sample()
                call_count["n"] = 0

                with monitor.sample() as result:
                    time.sleep(0.01)

                # delta = (2000 - 1000) * 15.3 = 15300 uJ = 0.0153 J
                expected_joules = (2000.0 - 1000.0) * 15.3 / 1e6
                assert result.energy_joules == pytest.approx(expected_joules)
                assert result.gpu_energy_joules == pytest.approx(expected_joules)
                assert_sample_result_basics(
                    result, vendor="amd", energy_method="hw_counter"
                )
            finally:
                mod._AMDSMI_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: sample() with no devices
# ---------------------------------------------------------------------------


class TestSampleNoDevices:
    def test_no_devices_empty_result(self):
        """When no AMD GPUs present, sample yields empty result."""
        from openjarvis.telemetry.energy_amd import AmdEnergyMonitor

        monitor = AmdEnergyMonitor.__new__(AmdEnergyMonitor)
        monitor._poll_interval_ms = 50
        monitor._handles = []
        monitor._device_count = 0
        monitor._device_name = ""
        monitor._initialized = False

        with monitor.sample() as result:
            pass

        assert_empty_sample_result(result, vendor="amd")


# ---------------------------------------------------------------------------
# Tests: close()
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_calls_amdsmi_shut_down(self):
        fake_amdsmi = _make_fake_amdsmi(device_count=1)

        with patch.dict(sys.modules, {"amdsmi": fake_amdsmi}):
            import openjarvis.telemetry.energy_amd as mod

            orig = mod._AMDSMI_AVAILABLE
            mod._AMDSMI_AVAILABLE = True
            mod.amdsmi = fake_amdsmi
            try:
                monitor = mod.AmdEnergyMonitor(poll_interval_ms=50)
                assert monitor._initialized is True

                fake_amdsmi.amdsmi_shut_down.reset_mock()
                assert_close_sets_uninitialized(monitor)
                fake_amdsmi.amdsmi_shut_down.assert_called_once()
            finally:
                mod._AMDSMI_AVAILABLE = orig
