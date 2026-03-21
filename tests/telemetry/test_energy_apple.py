"""Tests for AppleEnergyMonitor -- mock zeus (no real Apple Silicon required)."""

from __future__ import annotations

import time
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: build a fake zeus module
# ---------------------------------------------------------------------------


def _make_fake_zeus():
    """Return a fake zeus.device.soc.apple module with AppleSiliconMonitor."""
    # Build the nested module hierarchy
    zeus = types.ModuleType("zeus")
    zeus_device = types.ModuleType("zeus.device")
    zeus_device_soc = types.ModuleType("zeus.device.soc")
    zeus_device_soc_apple = types.ModuleType("zeus.device.soc.apple")

    mock_monitor_cls = MagicMock()
    zeus_device_soc_apple.AppleSiliconMonitor = mock_monitor_cls

    zeus.device = zeus_device
    zeus_device.soc = zeus_device_soc
    zeus_device_soc.apple = zeus_device_soc_apple

    return zeus, zeus_device, zeus_device_soc, zeus_device_soc_apple, mock_monitor_cls


# ---------------------------------------------------------------------------
# Tests: available()
# ---------------------------------------------------------------------------


class TestAvailable:
    def test_available_false_on_non_darwin(self):
        with patch("platform.system", return_value="Linux"):
            from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

            assert AppleEnergyMonitor.available() is False

    def test_available_true_without_zeus(self):
        """Monitor is available on Apple Silicon even without Zeus."""
        import openjarvis.telemetry.energy_apple as mod

        orig = mod._ZEUS_APPLE_AVAILABLE
        mod._ZEUS_APPLE_AVAILABLE = False
        try:
            with (
                patch("platform.system", return_value="Darwin"),
                patch("platform.machine", return_value="arm64"),
            ):
                assert mod.AppleEnergyMonitor.available() is True
                monitor = mod.AppleEnergyMonitor.__new__(mod.AppleEnergyMonitor)
                monitor._zeus_ok = False
                assert monitor.energy_method() == "cpu_time_estimate"
        finally:
            mod._ZEUS_APPLE_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: energy_method()
# ---------------------------------------------------------------------------


class TestEnergyMethod:
    def test_returns_zeus(self):
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        monitor = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
        monitor._zeus_ok = True
        assert monitor.energy_method() == "zeus"


# ---------------------------------------------------------------------------
# Tests: sample() component breakdown
# ---------------------------------------------------------------------------


class TestSampleComponentBreakdown:
    def test_component_energy_extraction(self):
        """Mock begin_window/end_window and verify cpu/gpu/dram/ane extraction."""
        mock_measurement = MagicMock()
        mock_measurement.cpu_energy = 1.5
        mock_measurement.gpu_energy = 3.0
        mock_measurement.dram_energy = 0.5
        mock_measurement.ane_energy = 2.0

        mock_zeus_monitor = MagicMock()
        mock_zeus_monitor.begin_window = MagicMock()
        mock_zeus_monitor.end_window = MagicMock(return_value=mock_measurement)

        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        monitor = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
        monitor._poll_interval_ms = 50
        monitor._monitor = mock_zeus_monitor
        monitor._zeus_ok = True
        monitor._chip_name = "M1"

        with monitor.sample() as result:
            time.sleep(0.01)

        mock_zeus_monitor.begin_window.assert_called_once()
        mock_zeus_monitor.end_window.assert_called_once()

        assert result.cpu_energy_joules == pytest.approx(1.5)
        assert result.gpu_energy_joules == pytest.approx(3.0)
        assert result.dram_energy_joules == pytest.approx(0.5)
        assert result.ane_energy_joules == pytest.approx(2.0)
        assert result.vendor == "apple"
        assert result.energy_method == "zeus"

    def test_total_energy_is_sum_of_components(self):
        """total = cpu + gpu + dram + ane."""
        mock_measurement = MagicMock()
        mock_measurement.cpu_energy = 1.0
        mock_measurement.gpu_energy = 2.0
        mock_measurement.dram_energy = 0.3
        mock_measurement.ane_energy = 0.7

        mock_zeus_monitor = MagicMock()
        mock_zeus_monitor.begin_window = MagicMock()
        mock_zeus_monitor.end_window = MagicMock(return_value=mock_measurement)

        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        monitor = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
        monitor._poll_interval_ms = 50
        monitor._monitor = mock_zeus_monitor
        monitor._zeus_ok = True
        monitor._chip_name = "M1"

        with monitor.sample() as result:
            pass

        expected_total = 1.0 + 2.0 + 0.3 + 0.7
        assert result.energy_joules == pytest.approx(expected_total)


# ---------------------------------------------------------------------------
# Tests: sample() with uninitialized monitor
# ---------------------------------------------------------------------------


class TestSampleUninitialized:
    def test_uninitialized_monitor_empty_result(self):
        """When monitor is not initialized, sample yields empty result."""
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        monitor = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
        monitor._poll_interval_ms = 50
        monitor._monitor = None
        monitor._zeus_ok = False
        monitor._chip_name = "Apple Silicon"
        monitor._tdp_watts = 20.0

        with monitor.sample() as result:
            pass

        # CPU-time fallback produces small but non-zero estimates
        assert result.energy_joules >= 0.0
        assert result.cpu_energy_joules >= 0.0
        assert result.gpu_energy_joules >= 0.0
        assert result.dram_energy_joules >= 0.0
        assert result.ane_energy_joules >= 0.0
        assert result.duration_seconds >= 0
        assert result.vendor == "apple"
        assert result.energy_method == "cpu_time_estimate"
