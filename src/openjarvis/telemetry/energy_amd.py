"""AMD energy monitor — hardware counters via amdsmi (ROCm 6.1+)."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Generator, List, Tuple

from openjarvis.telemetry.energy_monitor import (
    EnergyMonitor,
    EnergySample,
    EnergyVendor,
)

logger = logging.getLogger(__name__)

try:
    import amdsmi

    _AMDSMI_AVAILABLE = True
except ImportError:
    _AMDSMI_AVAILABLE = False


class AmdEnergyMonitor(EnergyMonitor):
    """AMD GPU energy monitor using amdsmi hardware counters.

    Uses ``amdsmi_get_energy_count()`` to read per-device energy accumulators.
    Energy = accumulator_delta * counter_resolution (microjoules), then / 1e6.
    """

    def __init__(self, poll_interval_ms: int = 50) -> None:
        self._poll_interval_ms = poll_interval_ms
        self._handles: List = []
        self._device_count = 0
        self._device_name = ""
        self._initialized = False

        if _AMDSMI_AVAILABLE:
            try:
                amdsmi.amdsmi_init()
                self._handles = amdsmi.amdsmi_get_processor_handles()
                self._device_count = len(self._handles)
                if self._handles:
                    info = amdsmi.amdsmi_get_gpu_asic_info(self._handles[0])
                    self._device_name = info.get("market_name", "AMD GPU")
                self._initialized = True
            except Exception as exc:
                logger.debug("AMD SMI initialization failed: %s", exc)
                self._initialized = False

    @staticmethod
    def available() -> bool:
        if not _AMDSMI_AVAILABLE:
            return False
        try:
            amdsmi.amdsmi_init()
            handles = amdsmi.amdsmi_get_processor_handles()
            amdsmi.amdsmi_shut_down()
            return len(handles) > 0
        except Exception as exc:
            logger.debug("AMD energy monitor availability check failed: %s", exc)
            return False

    def vendor(self) -> EnergyVendor:
        return EnergyVendor.AMD

    def energy_method(self) -> str:
        return "hw_counter"

    def _read_energy_counters(self) -> List[Tuple[float, float]]:
        """Read (accumulator, resolution) pairs from all devices."""
        readings: List[Tuple[float, float]] = []
        for handle in self._handles:
            try:
                info = amdsmi.amdsmi_get_energy_count(handle)
                accumulator = float(info.get("energy_accumulator", 0))
                resolution = float(info.get("counter_resolution", 1.0))
                readings.append((accumulator, resolution))
            except Exception as exc:
                logger.debug("Failed to read AMD GPU power: %s", exc)
                readings.append((0.0, 1.0))
        return readings

    @contextmanager
    def sample(self) -> Generator[EnergySample, None, None]:
        result = EnergySample(
            vendor=EnergyVendor.AMD.value,
            device_name=self._device_name,
            device_count=self._device_count,
            energy_method=self.energy_method(),
        )

        if not self._initialized or self._device_count == 0:
            t_start = time.monotonic()
            yield result
            result.duration_seconds = time.monotonic() - t_start
            return

        # Read energy counters at start
        start_readings = self._read_energy_counters()
        t_start = time.monotonic()

        yield result

        wall = time.monotonic() - t_start

        # Read energy counters at end
        end_readings = self._read_energy_counters()

        # Compute total energy from counter deltas
        total_energy_uj = 0.0
        for (start_acc, start_res), (end_acc, end_res) in zip(
            start_readings, end_readings
        ):
            delta = end_acc - start_acc
            # Use end resolution (should be same as start)
            total_energy_uj += delta * end_res

        # Convert microjoules to joules
        result.energy_joules = total_energy_uj / 1e6
        result.gpu_energy_joules = result.energy_joules
        result.duration_seconds = wall
        if wall > 0:
            result.mean_power_watts = result.energy_joules / wall

    def close(self) -> None:
        if self._initialized:
            try:
                amdsmi.amdsmi_shut_down()
            except Exception as exc:
                logger.debug("Failed to shut down AMD energy monitor: %s", exc)
            self._initialized = False


__all__ = ["AmdEnergyMonitor"]
