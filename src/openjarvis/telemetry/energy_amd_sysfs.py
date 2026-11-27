"""AMD GPU energy monitoring via amdgpu hwmon sysfs.

Why this exists alongside ``energy_amd`` (amdsmi): on integrated AMD graphics
-- Ryzen AI MAX / Strix Halo (gfx1151) and similar APUs -- ``amdsmi`` loads,
enumerates a device, and then fails every metric call with
``AMDSMI_STATUS_UNEXPECTED_DATA``. The kernel's amdgpu hwmon interface reports
power and temperature on exactly that hardware, is world-readable, and costs a
file read rather than a library call.

Energy is integrated from instantaneous power (``J = sum(P * dt)``) because
amdgpu exposes no energy accumulator, so ``energy_method`` is ``polling``
rather than ``hw_counter``. The rail read is ``power1_average``, which is the
GPU rail -- on an APU that is a subset of socket power, not the whole package.
"""

from __future__ import annotations

import glob
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Generator, Optional

from openjarvis.telemetry.energy_monitor import (
    BASIS_GPU,
    EnergyMonitor,
    EnergySample,
    EnergyVendor,
)

logger = logging.getLogger(__name__)

_HWMON_GLOB = "/sys/class/drm/card*/device/hwmon/hwmon*"


def _read_int(path: str) -> Optional[int]:
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _find_amdgpu_hwmon() -> Optional[str]:
    """Return the first amdgpu hwmon directory exposing a readable power rail."""
    for hwmon in sorted(glob.glob(_HWMON_GLOB)):
        name_path = os.path.join(hwmon, "name")
        try:
            with open(name_path) as fh:
                if fh.read().strip() != "amdgpu":
                    continue
        except OSError:
            continue
        for rail in ("power1_average", "power1_input"):
            if _read_int(os.path.join(hwmon, rail)) is not None:
                return hwmon
    return None


class AmdSysfsEnergyMonitor(EnergyMonitor):
    """Poll amdgpu hwmon power/temperature and integrate energy."""

    def __init__(self, poll_interval_ms: int = 50) -> None:
        self._poll_s = max(poll_interval_ms, 1) / 1000.0
        self._hwmon = _find_amdgpu_hwmon()
        self._power_path = ""
        self._temp_path = ""
        self._busy_path = ""
        self._device_name = "AMD GPU"
        if self._hwmon:
            for rail in ("power1_average", "power1_input"):
                candidate = os.path.join(self._hwmon, rail)
                if _read_int(candidate) is not None:
                    self._power_path = candidate
                    break
            temp = os.path.join(self._hwmon, "temp1_input")
            if _read_int(temp) is not None:
                self._temp_path = temp
            # hwmon lives at <card>/device/hwmon/hwmonN; busy is on <card>/device.
            device_dir = os.path.dirname(os.path.dirname(self._hwmon))
            busy = os.path.join(device_dir, "gpu_busy_percent")
            if _read_int(busy) is not None:
                self._busy_path = busy
            self._device_name = self._read_device_name(device_dir)
        self._stop = threading.Event()

    @staticmethod
    def _read_device_name(device_dir: str) -> str:
        for attr in ("product_name", "device"):
            try:
                with open(os.path.join(device_dir, attr)) as fh:
                    value = fh.read().strip()
                    if value:
                        return value
            except OSError:
                continue
        return "AMD GPU"

    @staticmethod
    def available() -> bool:
        return _find_amdgpu_hwmon() is not None

    def vendor(self) -> EnergyVendor:
        return EnergyVendor.AMD

    def energy_method(self) -> str:
        # Integrated from power samples, not read from a hardware accumulator.
        return "polling"

    def _read_power_watts(self) -> Optional[float]:
        micro = _read_int(self._power_path) if self._power_path else None
        return None if micro is None else micro / 1e6

    def snapshot(self) -> EnergySample:
        sample = EnergySample(
            vendor=EnergyVendor.AMD.value,
            device_name=self._device_name,
            device_count=1 if self._power_path else 0,
            energy_method=self.energy_method(),
            basis=BASIS_GPU,
        )
        watts = self._read_power_watts()
        if watts is not None:
            sample.mean_power_watts = watts
            sample.peak_power_watts = watts
            sample.gpu_power_watts = watts
            sample.num_snapshots = 1
        if self._temp_path:
            milli = _read_int(self._temp_path)
            if milli is not None:
                sample.mean_temperature_c = milli / 1000.0
                sample.peak_temperature_c = sample.mean_temperature_c
        if self._busy_path:
            busy = _read_int(self._busy_path)
            if busy is not None:
                sample.mean_utilization_pct = float(busy)
                sample.peak_utilization_pct = float(busy)
        return sample

    @contextmanager
    def sample(self) -> Generator[EnergySample, None, None]:
        result = EnergySample(
            vendor=EnergyVendor.AMD.value,
            device_name=self._device_name,
            device_count=1 if self._power_path else 0,
            energy_method=self.energy_method(),
            basis=BASIS_GPU,
        )

        if not self._power_path:
            t_start = time.monotonic()
            yield result
            result.duration_seconds = time.monotonic() - t_start
            return

        energy_j = 0.0
        peak_w = 0.0
        power_sum = 0.0
        temp_sum = 0.0
        util_sum = 0.0
        peak_temp = 0.0
        peak_util = 0.0
        count = 0
        stop = threading.Event()

        def poll() -> None:
            nonlocal energy_j, peak_w, power_sum, temp_sum, util_sum
            nonlocal peak_temp, peak_util, count
            last = time.monotonic()
            while not stop.is_set():
                stop.wait(self._poll_s)
                now = time.monotonic()
                dt = now - last
                last = now
                watts = self._read_power_watts()
                if watts is None:
                    continue
                # Rectangular integration over the elapsed interval.
                energy_j += watts * dt
                power_sum += watts
                peak_w = max(peak_w, watts)
                count += 1
                if self._temp_path:
                    milli = _read_int(self._temp_path)
                    if milli is not None:
                        celsius = milli / 1000.0
                        temp_sum += celsius
                        peak_temp = max(peak_temp, celsius)
                if self._busy_path:
                    busy = _read_int(self._busy_path)
                    if busy is not None:
                        util_sum += busy
                        peak_util = max(peak_util, float(busy))

        thread = threading.Thread(target=poll, name="amdgpu-energy", daemon=True)
        t_start = time.monotonic()
        thread.start()
        try:
            yield result
        finally:
            stop.set()
            thread.join(timeout=max(self._poll_s * 4, 0.5))

        wall = time.monotonic() - t_start
        result.duration_seconds = wall
        result.num_snapshots = count
        result.energy_joules = energy_j
        result.gpu_energy_joules = energy_j
        result.soc_energy_joules = energy_j
        result.peak_power_watts = peak_w
        if count:
            result.mean_power_watts = power_sum / count
            result.mean_temperature_c = temp_sum / count if temp_sum else 0.0
            result.mean_utilization_pct = util_sum / count if util_sum else 0.0
            result.peak_temperature_c = peak_temp
            result.peak_utilization_pct = peak_util
        elif wall > 0:
            result.mean_power_watts = energy_j / wall

    def close(self) -> None:
        self._stop.set()


__all__ = ["AmdSysfsEnergyMonitor"]
