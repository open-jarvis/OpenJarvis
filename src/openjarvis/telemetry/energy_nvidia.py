"""NVIDIA energy monitor — hardware counters (Volta+) with polling fallback."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Generator, List, Optional, Tuple

from openjarvis.telemetry.energy_monitor import (
    EnergyMonitor,
    EnergySample,
    EnergyVendor,
)

logger = logging.getLogger(__name__)

try:
    import pynvml

    _PYNVML_AVAILABLE = True
except ImportError:
    _PYNVML_AVAILABLE = False


class NvidiaEnergyMonitor(EnergyMonitor):
    """NVIDIA energy monitor using pynvml.

    **Primary mode** (Volta+): Reads ``nvmlDeviceGetTotalEnergyConsumption()``
    start/end hardware counters (millijoules).  Delta / 1000 = joules.

    **Fallback mode** (pre-Volta): Trapezoidal integration of
    ``nvmlDeviceGetPowerUsage()`` — same algorithm as legacy ``GpuMonitor``.

    A lightweight polling thread still runs in both modes for utilization,
    memory, and temperature metrics (no hw counter for those).
    """

    def __init__(self, poll_interval_ms: int = 50) -> None:
        self._poll_interval_s = poll_interval_ms / 1000.0
        self._handles: List = []
        self._device_count = 0
        self._device_name = ""
        self._initialized = False
        self._hw_counter_available = False

        if _PYNVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self._device_count = pynvml.nvmlDeviceGetCount()
                self._handles = [
                    pynvml.nvmlDeviceGetHandleByIndex(i)
                    for i in range(self._device_count)
                ]
                if self._handles:
                    self._device_name = pynvml.nvmlDeviceGetName(self._handles[0])
                    if isinstance(self._device_name, bytes):
                        self._device_name = self._device_name.decode()
                self._initialized = True
                self._hw_counter_available = self._probe_hw_counter()
            except Exception as exc:
                logger.debug("NVIDIA energy monitor initialization failed: %s", exc)
                self._initialized = False

    def _probe_hw_counter(self) -> bool:
        """Test if hardware energy counters are available (Volta+)."""
        if not self._handles:
            return False
        try:
            pynvml.nvmlDeviceGetTotalEnergyConsumption(self._handles[0])
            return True
        except Exception as exc:
            logger.debug("NVIDIA energy query support check failed: %s", exc)
            return False

    @staticmethod
    def available() -> bool:
        if not _PYNVML_AVAILABLE:
            return False
        try:
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            pynvml.nvmlShutdown()
            return count > 0
        except Exception as exc:
            logger.debug("NVIDIA energy monitor availability check failed: %s", exc)
            return False

    def vendor(self) -> EnergyVendor:
        return EnergyVendor.NVIDIA

    def energy_method(self) -> str:
        return "hw_counter" if self._hw_counter_available else "polling"

    def _read_energy_counters(self) -> List[float]:
        """Read total energy (millijoules) from all devices."""
        readings: List[float] = []
        for handle in self._handles:
            try:
                mj = pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)
                readings.append(float(mj))
            except Exception as exc:
                logger.debug("Failed to read NVIDIA GPU power: %s", exc)
                readings.append(0.0)
        return readings

    def _poll_once(self) -> Tuple[List[float], List[float], List[float], List[float]]:
        """Read power/utilization/memory/temperature from all devices."""
        powers: List[float] = []
        utils: List[float] = []
        mems: List[float] = []
        temps: List[float] = []
        for handle in self._handles:
            try:
                power_mw = pynvml.nvmlDeviceGetPowerUsage(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                powers.append(power_mw / 1000.0)
                utils.append(float(util.gpu))
                mems.append(mem_info.used / (1024**3))
                temps.append(float(temp))
            except Exception as exc:
                logger.debug("Failed to read NVIDIA GPU metrics: %s", exc)
        return powers, utils, mems, temps

    def _polling_loop(
        self,
        power_ticks: List[List[float]],
        util_ticks: List[float],
        mem_ticks: List[float],
        temp_ticks: List[float],
        timestamps: List[float],
        lock: threading.Lock,
        stop_event: threading.Event,
    ) -> None:
        """Background thread: poll GPUs until stop_event is set."""
        while not stop_event.is_set():
            powers, utils, mems, temps = self._poll_once()
            if powers:
                now = time.monotonic()
                with lock:
                    power_ticks.append(powers)
                    util_ticks.append(sum(utils) / len(utils) if utils else 0.0)
                    mem_ticks.append(sum(mems))
                    temp_ticks.append(sum(temps) / len(temps) if temps else 0.0)
                    timestamps.append(now)
            stop_event.wait(self._poll_interval_s)

    @contextmanager
    def sample(self) -> Generator[EnergySample, None, None]:
        result = EnergySample(
            vendor=EnergyVendor.NVIDIA.value,
            device_name=self._device_name,
            device_count=self._device_count,
            energy_method=self.energy_method(),
        )

        if not self._initialized or self._device_count == 0:
            t_start = time.monotonic()
            yield result
            result.duration_seconds = time.monotonic() - t_start
            return

        # Read hw counters at start
        energy_start: Optional[List[float]] = None
        if self._hw_counter_available:
            energy_start = self._read_energy_counters()

        # Start polling thread for utilization metrics + fallback power
        power_ticks: List[List[float]] = []
        util_ticks: List[float] = []
        mem_ticks: List[float] = []
        temp_ticks: List[float] = []
        timestamps: List[float] = []
        lock = threading.Lock()
        stop_event = threading.Event()

        thread = threading.Thread(
            target=self._polling_loop,
            args=(
                power_ticks,
                util_ticks,
                mem_ticks,
                temp_ticks,
                timestamps,
                lock,
                stop_event,
            ),
            daemon=True,
        )

        t_start = time.monotonic()
        thread.start()
        try:
            yield result
        finally:
            stop_event.set()
            thread.join(timeout=2.0)
            wall = time.monotonic() - t_start

            # Read hw counters at end
            if self._hw_counter_available and energy_start is not None:
                energy_end = self._read_energy_counters()
                total_mj = sum(
                    end - start for start, end in zip(energy_start, energy_end)
                )
                result.energy_joules = total_mj / 1000.0
                result.gpu_energy_joules = result.energy_joules
            else:
                # Fallback: trapezoidal integration
                with lock:
                    p_copy = list(power_ticks)
                    ts_copy = list(timestamps)
                energy = 0.0
                for i in range(1, len(ts_copy)):
                    dt = ts_copy[i] - ts_copy[i - 1]
                    p_prev = sum(p_copy[i - 1])
                    p_curr = sum(p_copy[i])
                    energy += 0.5 * (p_prev + p_curr) * dt
                result.energy_joules = energy
                result.gpu_energy_joules = energy

            # Aggregate utilization metrics from polling data
            with lock:
                pt_copy = [sum(p) for p in power_ticks]
                ut_copy = list(util_ticks)
                mt_copy = list(mem_ticks)
                tt_copy = list(temp_ticks)

            n = len(pt_copy)
            if n > 0:
                result.mean_power_watts = sum(pt_copy) / n
                result.peak_power_watts = max(pt_copy)
                result.mean_utilization_pct = sum(ut_copy) / n
                result.peak_utilization_pct = max(ut_copy)
                result.mean_memory_used_gb = sum(mt_copy) / n
                result.peak_memory_used_gb = max(mt_copy)
                result.mean_temperature_c = sum(tt_copy) / n
                result.peak_temperature_c = max(tt_copy)

            result.duration_seconds = wall
            result.num_snapshots = n

    def close(self) -> None:
        if self._initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception as exc:
                logger.debug("Failed to shut down NVIDIA energy monitor: %s", exc)
            self._initialized = False


__all__ = ["NvidiaEnergyMonitor"]
