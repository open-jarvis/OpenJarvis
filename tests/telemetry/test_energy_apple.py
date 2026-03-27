"""Tests for AppleEnergyMonitor -- mock zeus (no real Apple Silicon required)."""

from __future__ import annotations

import time
import types
from unittest.mock import MagicMock, call, patch

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
                monitor._battery_ok = False
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
        monitor._battery_ok = False
        assert monitor.energy_method() == "zeus"

    def test_returns_battery_drain_when_battery_ok(self):
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        monitor = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
        monitor._zeus_ok = False
        monitor._battery_ok = True
        assert monitor.energy_method() == "battery_drain"

    def test_returns_cpu_time_estimate_as_last_resort(self):
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        monitor = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
        monitor._zeus_ok = False
        monitor._battery_ok = False
        assert monitor.energy_method() == "cpu_time_estimate"


# ---------------------------------------------------------------------------
# Tests: sample() component breakdown — zeus path
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
        monitor._battery_ok = False
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
        monitor._battery_ok = False
        monitor._chip_name = "M1"

        with monitor.sample() as result:
            pass

        expected_total = 1.0 + 2.0 + 0.3 + 0.7
        assert result.energy_joules == pytest.approx(expected_total)


# ---------------------------------------------------------------------------
# Tests: sample() — battery drain path
# ---------------------------------------------------------------------------


class TestSampleBatteryDrain:
    def _make_monitor(self):
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        monitor = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
        monitor._poll_interval_ms = 50
        monitor._monitor = None
        monitor._zeus_ok = False
        monitor._battery_ok = True
        monitor._chip_name = "M2 Pro"
        monitor._tdp_watts = 30.0
        return monitor

    def test_battery_drain_on_battery(self):
        """Battery path reports battery_drain method and positive energy."""
        from openjarvis.telemetry.energy_apple import _BatteryPoller

        monitor = self._make_monitor()

        fake_samples = [(0.1, 5.0), (0.6, 6.0), (1.1, 5.5)]

        with (
            patch.object(_BatteryPoller, "start"),
            patch.object(_BatteryPoller, "stop", return_value=fake_samples),
            patch.object(_BatteryPoller, "on_battery", new_callable=lambda: property(lambda self: True)),
            patch("time.monotonic", side_effect=[0.0, 1.2]),
        ):
            with monitor.sample() as result:
                pass

        assert result.energy_joules > 0
        assert result.mean_power_watts > 0
        assert result.duration_seconds == pytest.approx(1.2)
        assert result.energy_method == "battery_drain"
        assert result.vendor == "apple"

    def test_battery_drain_on_ac_sets_method(self):
        """When on AC, energy_method is battery_drain_ac."""
        from openjarvis.telemetry.energy_apple import _BatteryPoller

        monitor = self._make_monitor()
        fake_samples = [(0.1, 10.0), (0.6, 10.0)]

        with (
            patch.object(_BatteryPoller, "start"),
            patch.object(_BatteryPoller, "stop", return_value=fake_samples),
            patch.object(_BatteryPoller, "on_battery", new_callable=lambda: property(lambda self: False)),
            patch("time.monotonic", side_effect=[0.0, 1.0]),
        ):
            with monitor.sample() as result:
                pass

        assert result.energy_method == "battery_drain_ac"

    def test_battery_component_split_sums_to_total(self):
        """CPU+GPU+DRAM+ANE components sum to total energy."""
        from openjarvis.telemetry.energy_apple import _BatteryPoller

        monitor = self._make_monitor()
        fake_samples = [(0.1, 8.0), (0.6, 8.0)]

        with (
            patch.object(_BatteryPoller, "start"),
            patch.object(_BatteryPoller, "stop", return_value=fake_samples),
            patch.object(_BatteryPoller, "on_battery", new_callable=lambda: property(lambda self: True)),
            patch("time.monotonic", side_effect=[0.0, 1.0]),
        ):
            with monitor.sample() as result:
                pass

        component_sum = (
            result.cpu_energy_joules
            + result.gpu_energy_joules
            + result.dram_energy_joules
            + result.ane_energy_joules
        )
        assert component_sum == pytest.approx(result.energy_joules, rel=1e-6)

    def test_battery_no_samples_yields_zero_energy(self):
        """When poller returns no samples, energy is zero."""
        from openjarvis.telemetry.energy_apple import _BatteryPoller

        monitor = self._make_monitor()

        with (
            patch.object(_BatteryPoller, "start"),
            patch.object(_BatteryPoller, "stop", return_value=[]),
            patch.object(_BatteryPoller, "on_battery", new_callable=lambda: property(lambda self: True)),
            patch("time.monotonic", side_effect=[0.0, 0.5]),
        ):
            with monitor.sample() as result:
                pass

        assert result.energy_joules == pytest.approx(0.0)
        assert result.duration_seconds == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Tests: _trapezoid integration
# ---------------------------------------------------------------------------


class TestTrapezoid:
    def test_single_sample_constant_power(self):
        """One sample: zero-order hold covers full interval."""
        from openjarvis.telemetry.energy_apple import _trapezoid

        samples = [(0.5, 10.0)]  # 10W at t=0.5
        energy = _trapezoid(samples, t_start=0.0, t_end=1.0)
        # Leading: 10W × 0.5s = 5J; trailing: 10W × 0.5s = 5J
        assert energy == pytest.approx(10.0, rel=1e-6)

    def test_two_samples_trapezoidal(self):
        """Two samples: trapezoid over interior + boundary segments."""
        from openjarvis.telemetry.energy_apple import _trapezoid

        samples = [(0.2, 4.0), (0.8, 8.0)]
        energy = _trapezoid(samples, t_start=0.0, t_end=1.0)
        # Leading: 4W × 0.2s = 0.8J
        # Interior: avg(4,8)W × 0.6s = 6W × 0.6s = 3.6J
        # Trailing: 8W × 0.2s = 1.6J
        assert energy == pytest.approx(0.8 + 3.6 + 1.6, rel=1e-6)

    def test_constant_power_exact(self):
        """Constant power: energy = power × duration regardless of sample count."""
        from openjarvis.telemetry.energy_apple import _trapezoid

        power = 5.0
        samples = [(0.25 * i, power) for i in range(1, 4)]  # t=0.25,0.5,0.75
        energy = _trapezoid(samples, t_start=0.0, t_end=1.0)
        assert energy == pytest.approx(power * 1.0, rel=1e-6)

    def test_empty_samples_returns_zero(self):
        from openjarvis.telemetry.energy_apple import _trapezoid

        assert _trapezoid([], t_start=0.0, t_end=1.0) == pytest.approx(0.0)

    def test_zero_duration_returns_zero(self):
        from openjarvis.telemetry.energy_apple import _trapezoid

        assert _trapezoid([(0.5, 10.0)], t_start=1.0, t_end=1.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests: _read_battery_watts
# ---------------------------------------------------------------------------


class TestReadBatteryWatts:
    def test_parses_discharge_rate_and_voltage(self):
        """Happy-path: discharging battery returns (watts, on_battery=True)."""
        import plistlib
        from openjarvis.telemetry.energy_apple import _read_battery_watts

        fake_plist = plistlib.dumps([{
            "CurrentDischargeRate": 2000,   # 2000 mA
            "Voltage": 12000,               # 12000 mV → 12V
            "IsCharging": False,
            "ExternalConnected": False,
        }])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_plist)
            result = _read_battery_watts()

        assert result is not None
        watts, on_battery = result
        assert watts == pytest.approx(24.0, rel=1e-6)  # 2A × 12V
        assert on_battery is True

    def test_ac_connected_sets_on_battery_false(self):
        import plistlib
        from openjarvis.telemetry.energy_apple import _read_battery_watts

        fake_plist = plistlib.dumps([{
            "CurrentDischargeRate": 500,
            "Voltage": 12000,
            "IsCharging": False,
            "ExternalConnected": True,
        }])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_plist)
            result = _read_battery_watts()

        assert result is not None
        _, on_battery = result
        assert on_battery is False

    def test_charging_suppresses_noise(self):
        """When IsCharging=True and watts < 0.5, return 0.0 watts."""
        import plistlib
        from openjarvis.telemetry.energy_apple import _read_battery_watts

        fake_plist = plistlib.dumps([{
            "CurrentDischargeRate": 10,
            "Voltage": 12000,
            "IsCharging": True,
            "ExternalConnected": True,
        }])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_plist)
            result = _read_battery_watts()

        assert result is not None
        watts, _ = result
        assert watts == pytest.approx(0.0)

    def test_returns_none_on_empty_output(self):
        from openjarvis.telemetry.energy_apple import _read_battery_watts

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"")
            result = _read_battery_watts()

        assert result is None

    def test_returns_none_on_subprocess_error(self):
        from openjarvis.telemetry.energy_apple import _read_battery_watts

        with patch("subprocess.run", side_effect=Exception("timeout")):
            result = _read_battery_watts()

        assert result is None

    def test_returns_none_on_nonzero_returncode(self):
        from openjarvis.telemetry.energy_apple import _read_battery_watts

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=b"")
            result = _read_battery_watts()

        assert result is None


# ---------------------------------------------------------------------------
# Tests: sample() with uninitialized monitor (cpu_time fallback)
# ---------------------------------------------------------------------------


class TestSampleUninitialized:
    def test_uninitialized_monitor_empty_result(self):
        """When no Zeus or battery, sample uses cpu_time_estimate fallback."""
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        monitor = AppleEnergyMonitor.__new__(AppleEnergyMonitor)
        monitor._poll_interval_ms = 50
        monitor._monitor = None
        monitor._zeus_ok = False
        monitor._battery_ok = False
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
