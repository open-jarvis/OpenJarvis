"""Tests for EnergyMonitor ABC, EnergySample, EnergyVendor, and factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.telemetry.energy_monitor import (
    EnergyMonitor,
    EnergySample,
    EnergyVendor,
    create_energy_monitor,
)

# ---------------------------------------------------------------------------
# Tests: EnergySample defaults
# ---------------------------------------------------------------------------


class TestEnergySample:
    def test_default_field_values(self):
        s = EnergySample()
        assert s.energy_joules == 0.0
        assert s.mean_power_watts == 0.0
        assert s.peak_power_watts == 0.0
        assert s.duration_seconds == 0.0
        assert s.num_snapshots == 0
        assert s.mean_utilization_pct == 0.0
        assert s.peak_utilization_pct == 0.0
        assert s.mean_memory_used_gb == 0.0
        assert s.peak_memory_used_gb == 0.0
        assert s.mean_temperature_c == 0.0
        assert s.peak_temperature_c == 0.0
        assert s.vendor == ""
        assert s.device_name == ""
        assert s.device_count == 0
        assert s.energy_method == ""
        assert s.cpu_energy_joules == 0.0
        assert s.gpu_energy_joules == 0.0
        assert s.dram_energy_joules == 0.0
        assert s.ane_energy_joules == 0.0


# ---------------------------------------------------------------------------
# Tests: EnergyVendor enum
# ---------------------------------------------------------------------------


class TestEnergyVendor:
    def test_enum_values(self):
        assert EnergyVendor.NVIDIA.value == "nvidia"
        assert EnergyVendor.AMD.value == "amd"
        assert EnergyVendor.APPLE.value == "apple"
        assert EnergyVendor.CPU_RAPL.value == "cpu_rapl"

    def test_enum_is_str(self):
        assert isinstance(EnergyVendor.NVIDIA, str)
        assert EnergyVendor.AMD == "amd"


# ---------------------------------------------------------------------------
# Tests: EnergyMonitor ABC
# ---------------------------------------------------------------------------


class TestEnergyMonitorABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            EnergyMonitor()


# ---------------------------------------------------------------------------
# Tests: create_energy_monitor factory
# ---------------------------------------------------------------------------


class TestCreateEnergyMonitor:
    def test_returns_none_when_nothing_available(self):
        with (
            patch(
                "openjarvis.telemetry.energy_nvidia.NvidiaEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_amd.AmdEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_apple.AppleEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_rapl.RaplEnergyMonitor.available",
                return_value=False,
            ),
        ):
            result = create_energy_monitor()
            assert result is None

    def test_prefer_vendor_parameter(self):
        """When prefer_vendor is set, that vendor is tried first."""
        with (
            patch(
                "openjarvis.telemetry.energy_nvidia.NvidiaEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_amd.AmdEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_apple.AppleEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_rapl.RaplEnergyMonitor.available",
                return_value=True,
            ),
            patch(
                "openjarvis.telemetry.energy_rapl.RaplEnergyMonitor.__init__",
                return_value=None,
            ) as mock_init,
        ):
            create_energy_monitor(prefer_vendor="cpu_rapl")
            # RaplEnergyMonitor was available and preferred
            mock_init.assert_called_once_with(poll_interval_ms=50)

    def test_detection_order_nvidia_first(self):
        """Default order: NVIDIA is tried before AMD."""
        call_order = []

        def nvidia_available():
            call_order.append("nvidia")
            return True

        def amd_available():
            call_order.append("amd")
            return True

        with (
            patch(
                "openjarvis.telemetry.energy_nvidia.NvidiaEnergyMonitor.available",
                side_effect=nvidia_available,
            ),
            patch(
                "openjarvis.telemetry.energy_amd.AmdEnergyMonitor.available",
                side_effect=amd_available,
            ),
            patch(
                "openjarvis.telemetry.energy_apple.AppleEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_rapl.RaplEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_nvidia.NvidiaEnergyMonitor.__init__",
                return_value=None,
            ),
        ):
            create_energy_monitor()
            # NVIDIA was tried first and returned True
            assert call_order == ["nvidia"]

    def test_detection_order_falls_through(self):
        """When NVIDIA unavailable, AMD is tried next."""
        call_order = []

        def nvidia_available():
            call_order.append("nvidia")
            return False

        def amd_available():
            call_order.append("amd")
            return True

        with (
            patch(
                "openjarvis.telemetry.energy_nvidia.NvidiaEnergyMonitor.available",
                side_effect=nvidia_available,
            ),
            patch(
                "openjarvis.telemetry.energy_amd.AmdEnergyMonitor.available",
                side_effect=amd_available,
            ),
            patch(
                "openjarvis.telemetry.energy_apple.AppleEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_rapl.RaplEnergyMonitor.available",
                return_value=False,
            ),
            patch(
                "openjarvis.telemetry.energy_amd.AmdEnergyMonitor.__init__",
                return_value=None,
            ),
        ):
            create_energy_monitor()
            assert call_order == ["nvidia", "amd"]

    def test_prefer_vendor_tried_first_then_default_order(self):
        """prefer_vendor=cpu_rapl puts RAPL first, then NVIDIA > AMD > Apple."""
        call_order = []

        def rapl_available():
            call_order.append("rapl")
            return False

        def nvidia_available():
            call_order.append("nvidia")
            return False

        def amd_available():
            call_order.append("amd")
            return False

        def apple_available():
            call_order.append("apple")
            return False

        with (
            patch(
                "openjarvis.telemetry.energy_nvidia.NvidiaEnergyMonitor.available",
                side_effect=nvidia_available,
            ),
            patch(
                "openjarvis.telemetry.energy_amd.AmdEnergyMonitor.available",
                side_effect=amd_available,
            ),
            patch(
                "openjarvis.telemetry.energy_apple.AppleEnergyMonitor.available",
                side_effect=apple_available,
            ),
            patch(
                "openjarvis.telemetry.energy_rapl.RaplEnergyMonitor.available",
                side_effect=rapl_available,
            ),
        ):
            result = create_energy_monitor(prefer_vendor="cpu_rapl")
            assert result is None
            assert call_order == ["rapl", "nvidia", "amd", "apple"]
