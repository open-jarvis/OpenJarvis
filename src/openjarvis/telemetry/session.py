"""Background-sampling telemetry session.

Uses Rust ring buffer — Rust backend is mandatory.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Deque, List, Optional

if TYPE_CHECKING:
    from openjarvis.telemetry.energy_monitor import EnergyMonitor

logger = logging.getLogger(__name__)


@dataclass
class TelemetrySample:
    """Single telemetry sample."""

    timestamp_ns: int
    gpu_power_w: float = 0.0
    cpu_power_w: float = 0.0
    gpu_energy_j: float = 0.0
    cpu_energy_j: float = 0.0
    gpu_util_pct: float = 0.0
    gpu_temp_c: float = 0.0
    gpu_mem_gb: float = 0.0


class _PythonRingBuffer:
    """Pure-Python fallback ring buffer."""

    def __init__(self, capacity: int = 100_000):
        self._data: Deque[TelemetrySample] = deque(maxlen=capacity)

    def push(self, sample: TelemetrySample) -> None:
        self._data.append(sample)

    def window(self, start_ns: int, end_ns: int) -> List[TelemetrySample]:
        return [s for s in self._data if start_ns <= s.timestamp_ns <= end_ns]

    def compute_energy_delta(self, start_ns: int, end_ns: int) -> tuple[float, float]:
        samples = self.window(start_ns, end_ns)
        if len(samples) < 2:
            return (0.0, 0.0)
        # Trapezoidal integration over power samples
        gpu_j = 0.0
        cpu_j = 0.0
        for i in range(1, len(samples)):
            dt = (samples[i].timestamp_ns - samples[i - 1].timestamp_ns) / 1e9
            gpu_j += 0.5 * (samples[i - 1].gpu_power_w + samples[i].gpu_power_w) * dt
            cpu_j += 0.5 * (samples[i - 1].cpu_power_w + samples[i].cpu_power_w) * dt
        return (gpu_j, cpu_j)

    def compute_avg_power(self, start_ns: int, end_ns: int) -> tuple[float, float]:
        samples = self.window(start_ns, end_ns)
        if not samples:
            return (0.0, 0.0)
        gpu_avg = sum(s.gpu_power_w for s in samples) / len(samples)
        cpu_avg = sum(s.cpu_power_w for s in samples) / len(samples)
        return (gpu_avg, cpu_avg)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class TelemetrySession:
    """Background-sampling telemetry session.

    Spawns a daemon thread that calls monitor.snapshot() at the configured
    interval. Stores samples in a ring buffer (Rust-backed if available,
    else pure-Python fallback).
    """

    def __init__(
        self,
        monitor: Optional[EnergyMonitor] = None,
        interval_ms: int = 100,
        buffer_size: int = 100_000,
    ) -> None:
        self._monitor = monitor
        self._interval_ms = interval_ms
        self._buffer = _PythonRingBuffer(buffer_size)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _sample_loop(self) -> None:
        """Daemon thread loop: poll monitor and push samples."""
        interval_s = self._interval_ms / 1000.0
        while not self._stop_event.is_set():
            try:
                if self._monitor is not None:
                    es = self._monitor.snapshot()
                    sample = TelemetrySample(
                        timestamp_ns=time.time_ns(),
                        gpu_power_w=es.mean_power_watts,
                        cpu_power_w=0.0,
                        gpu_energy_j=es.gpu_energy_joules,
                        cpu_energy_j=es.cpu_energy_joules,
                        gpu_util_pct=es.mean_utilization_pct,
                        gpu_temp_c=es.mean_temperature_c,
                        gpu_mem_gb=es.mean_memory_used_gb,
                    )
                    self._buffer.push(sample)
            except Exception as exc:
                logger.debug("Failed to record telemetry session: %s", exc)
            self._stop_event.wait(interval_s)

    def start(self) -> None:
        """Start background sampling thread."""
        if self._monitor is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop sampling thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def window(self, start_ns: int, end_ns: int) -> List[TelemetrySample]:
        return self._buffer.window(start_ns, end_ns)

    def energy_delta(self, start_ns: int, end_ns: int) -> tuple[float, float]:
        return self._buffer.compute_energy_delta(start_ns, end_ns)

    def avg_power(self, start_ns: int, end_ns: int) -> tuple[float, float]:
        return self._buffer.compute_avg_power(start_ns, end_ns)

    def __enter__(self) -> TelemetrySession:
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()
