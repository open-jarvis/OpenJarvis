"""EnergyMonitor ABC — multi-vendor energy measurement with hardware counters."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Generator, Optional

logger = logging.getLogger(__name__)


class EnergyVendor(str, Enum):
    """Supported energy measurement vendors."""

    NVIDIA = "nvidia"
    AMD = "amd"
    APPLE = "apple"
    CPU_RAPL = "cpu_rapl"


@dataclass
class EnergySample:
    """Aggregated energy metrics over an inference bracket.

    Superset of ``GpuSample`` — adds vendor, device info, energy method,
    and per-component breakdown (CPU, GPU, DRAM, ANE).
    """

    # Total energy (always populated)
    energy_joules: float = 0.0
    mean_power_watts: float = 0.0
    peak_power_watts: float = 0.0
    duration_seconds: float = 0.0
    num_snapshots: int = 0

    # GPU utilization metrics (populated by GPU vendors)
    mean_utilization_pct: float = 0.0
    peak_utilization_pct: float = 0.0
    mean_memory_used_gb: float = 0.0
    peak_memory_used_gb: float = 0.0
    mean_temperature_c: float = 0.0
    peak_temperature_c: float = 0.0

    # Vendor / device info
    vendor: str = ""
    device_name: str = ""
    device_count: int = 0
    energy_method: str = ""  # "hw_counter", "polling", "rapl", "zeus"

    # Per-component breakdown (joules)
    cpu_energy_joules: float = 0.0
    gpu_energy_joules: float = 0.0
    dram_energy_joules: float = 0.0
    ane_energy_joules: float = 0.0


class EnergyMonitor(ABC):
    """Abstract base class for energy measurement backends.

    Each vendor implementation probes for hardware support at init,
    exposes an ``available()`` class method, and provides a ``sample()``
    context manager that measures energy over a code block.
    """

    @staticmethod
    @abstractmethod
    def available() -> bool:
        """Return ``True`` if this monitor can run on the current hardware."""

    @abstractmethod
    def vendor(self) -> EnergyVendor:
        """Return the vendor enum for this monitor."""

    @abstractmethod
    def energy_method(self) -> str:
        """Return the measurement method: 'hw_counter', 'polling', 'rapl', or 'zeus'."""

    @abstractmethod
    @contextmanager
    def sample(self) -> Generator[EnergySample, None, None]:
        """Context manager that measures energy during the enclosed block.

        Yields an ``EnergySample`` that is populated when the block exits.
        """
        yield EnergySample()  # pragma: no cover

    def snapshot(self) -> EnergySample:
        """Return an instantaneous energy reading without start/stop bracket.

        Subclasses should override to provide actual readings. Default returns
        an empty sample.
        """
        return EnergySample()

    @abstractmethod
    def close(self) -> None:
        """Release any resources (handles, threads, etc.)."""


def create_energy_monitor(
    poll_interval_ms: int = 50,
    prefer_vendor: Optional[str] = None,
) -> Optional[EnergyMonitor]:
    """Factory — auto-detect and return the best available EnergyMonitor.

    Detection order: NVIDIA > AMD > Apple > CPU RAPL.
    If *prefer_vendor* is set, try that vendor first.

    Returns ``None`` if no energy monitoring is available.
    """
    # Build ordered candidate list — imports are defensive because vendor
    # packages (amdsmi, pynvml) may be installed but non-functional on the
    # current platform (e.g. amdsmi on macOS).
    vendor_map: dict[str, type[EnergyMonitor]] = {}
    default_order: list[type[EnergyMonitor]] = []

    try:
        from openjarvis.telemetry.energy_nvidia import NvidiaEnergyMonitor

        vendor_map["nvidia"] = NvidiaEnergyMonitor
        default_order.append(NvidiaEnergyMonitor)
    except Exception as exc:
        logger.debug("Failed to load NVIDIA energy monitor: %s", exc)

    try:
        from openjarvis.telemetry.energy_amd import AmdEnergyMonitor

        vendor_map["amd"] = AmdEnergyMonitor
        default_order.append(AmdEnergyMonitor)
    except Exception as exc:
        logger.debug("Failed to load AMD energy monitor: %s", exc)

    try:
        from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

        vendor_map["apple"] = AppleEnergyMonitor
        default_order.append(AppleEnergyMonitor)
    except Exception as exc:
        logger.debug("Failed to load Apple energy monitor: %s", exc)

    try:
        from openjarvis.telemetry.energy_rapl import RaplEnergyMonitor

        vendor_map["cpu_rapl"] = RaplEnergyMonitor
        default_order.append(RaplEnergyMonitor)
    except Exception as exc:
        logger.debug("Failed to load RAPL energy monitor: %s", exc)

    if prefer_vendor and prefer_vendor.lower() in vendor_map:
        preferred_cls = vendor_map[prefer_vendor.lower()]
        candidates = [preferred_cls] + [
            c for c in default_order if c is not preferred_cls
        ]
    else:
        candidates = default_order

    for cls in candidates:
        try:
            if cls.available():
                return cls(poll_interval_ms=poll_interval_ms)
        except Exception as exc:
            logger.debug("Energy monitor candidate failed: %s", exc)
            continue

    return None


__all__ = [
    "EnergyMonitor",
    "EnergySample",
    "EnergyVendor",
    "create_energy_monitor",
]
