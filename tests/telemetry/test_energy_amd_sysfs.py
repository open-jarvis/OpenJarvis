"""Tests for AmdSysfsEnergyMonitor -- mock amdgpu hwmon (no real GPU needed).

The monitor exists because amdsmi enumerates integrated AMD graphics (Strix
Halo / gfx1151) and then fails every metric call, so these tests pin the
behaviour that matters: real joules from sysfs, and no silent zeros.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.telemetry.energy_amd_sysfs import (
    AmdSysfsEnergyMonitor,
    _find_amdgpu_hwmon,
)
from openjarvis.telemetry.energy_monitor import BASIS_GPU, EnergyVendor

_GLOB = "openjarvis.telemetry.energy_amd_sysfs._HWMON_GLOB"


def _make_hwmon(
    base: Path,
    *,
    name: str = "amdgpu",
    power_uw: int | None = 17_384_000,
    temp_mc: int | None = 52_000,
    busy_pct: int | None = 37,
    card: str = "card1",
) -> str:
    """Build <base>/<card>/device/hwmon/hwmon0 and return the glob to match it."""
    device = base / card / "device"
    hwmon = device / "hwmon" / "hwmon0"
    hwmon.mkdir(parents=True)
    (hwmon / "name").write_text(f"{name}\n")
    if power_uw is not None:
        (hwmon / "power1_average").write_text(f"{power_uw}\n")
    if temp_mc is not None:
        (hwmon / "temp1_input").write_text(f"{temp_mc}\n")
    if busy_pct is not None:
        (device / "gpu_busy_percent").write_text(f"{busy_pct}\n")
    (device / "product_name").write_text("Radeon 8060S\n")
    return str(base / "card*" / "device" / "hwmon" / "hwmon*")


class TestDiscovery:
    def test_finds_amdgpu_hwmon(self, tmp_path):
        pattern = _make_hwmon(tmp_path)
        with patch(_GLOB, pattern):
            assert _find_amdgpu_hwmon() is not None
            assert AmdSysfsEnergyMonitor.available() is True

    def test_ignores_non_amdgpu_hwmon(self, tmp_path):
        pattern = _make_hwmon(tmp_path, name="nouveau")
        with patch(_GLOB, pattern):
            assert _find_amdgpu_hwmon() is None
            assert AmdSysfsEnergyMonitor.available() is False

    def test_unavailable_when_power_rail_missing(self, tmp_path):
        pattern = _make_hwmon(tmp_path, power_uw=None)
        with patch(_GLOB, pattern):
            assert AmdSysfsEnergyMonitor.available() is False


class TestSnapshot:
    def test_reports_power_temperature_and_utilization(self, tmp_path):
        pattern = _make_hwmon(tmp_path)
        with patch(_GLOB, pattern):
            monitor = AmdSysfsEnergyMonitor(poll_interval_ms=10)
        sample = monitor.snapshot()
        # 17_384_000 microwatts = 17.384 W; 52_000 millidegrees = 52 C.
        assert sample.mean_power_watts == pytest.approx(17.384)
        assert sample.mean_temperature_c == pytest.approx(52.0)
        assert sample.mean_utilization_pct == pytest.approx(37.0)
        assert sample.vendor == EnergyVendor.AMD.value

    def test_method_is_polling_not_hw_counter(self, tmp_path):
        """amdgpu exposes no energy accumulator, so joules are integrated.

        Mislabelling this as hw_counter would present modelled joules as
        directly measured ones.
        """
        pattern = _make_hwmon(tmp_path)
        with patch(_GLOB, pattern):
            monitor = AmdSysfsEnergyMonitor()
        assert monitor.energy_method() == "polling"


class TestSampling:
    def test_integrates_energy_over_the_block(self, tmp_path):
        pattern = _make_hwmon(tmp_path, power_uw=20_000_000)  # a steady 20 W
        with patch(_GLOB, pattern):
            monitor = AmdSysfsEnergyMonitor(poll_interval_ms=5)
            with monitor.sample() as sample:
                time.sleep(0.2)

        assert sample.num_snapshots > 0
        assert sample.duration_seconds == pytest.approx(0.2, abs=0.15)
        # ~20 W for ~0.2 s is ~4 J. Wide bounds: thread scheduling is noisy.
        assert 1.0 < sample.energy_joules < 12.0
        assert sample.mean_power_watts == pytest.approx(20.0, abs=0.5)
        assert sample.gpu_energy_joules == sample.energy_joules
        # Derived per-token figures must be attributed to the GPU rail.
        assert sample.basis == BASIS_GPU

    def test_no_power_rail_yields_zero_not_fake_energy(self, tmp_path):
        """With nothing readable the sample must stay empty.

        A zero that looks like a measurement is worse than an absent one; the
        amdsmi path shipped exactly that bug.
        """
        pattern = _make_hwmon(tmp_path, power_uw=None)
        with patch(_GLOB, pattern):
            monitor = AmdSysfsEnergyMonitor(poll_interval_ms=5)
        with monitor.sample() as sample:
            pass
        assert sample.energy_joules == 0.0
        assert sample.num_snapshots == 0
        assert sample.device_count == 0
