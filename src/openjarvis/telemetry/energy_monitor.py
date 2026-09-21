"""EnergyMonitor ABC — multi-vendor energy measurement with hardware counters."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Generator, Optional

logger = logging.getLogger(__name__)


# Rail sets that derived per-token / per-watt figures can be computed from.
# ``BASIS_SOC`` means CPU + GPU + ANE (+ DRAM where measured); ``BASIS_GPU``
# means the GPU rail alone. Energy and power must always be read from the
# *same* basis -- SoC joules divided by GPU watts is a meaningless number.
BASIS_SOC = "soc"
BASIS_GPU = "gpu"


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
    # How the numbers above were obtained. "hw_counter" / "polling" (NVIDIA,
    # AMD), "rapl" (Linux sysfs), "ioreport" (Apple Silicon), or
    # "tdp_estimate" -- the last being modelled rather than measured, and
    # opt-in.
    energy_method: str = ""

    # Per-component breakdown (joules)
    cpu_energy_joules: float = 0.0
    gpu_energy_joules: float = 0.0
    dram_energy_joules: float = 0.0
    ane_energy_joules: float = 0.0

    # Per-component instantaneous power (watts). Populated by monitors that
    # can attribute power per rail; ``snapshot()`` callers difference the
    # energy fields above and average these.
    cpu_power_watts: float = 0.0
    gpu_power_watts: float = 0.0
    ane_power_watts: float = 0.0

    # Whole-SoC energy: every rail this monitor measured, summed. On Apple
    # Silicon each rail above is a partial view -- a model that runs on the
    # Neural Engine draws almost nothing on the GPU rail -- so per-token
    # energy must be derived from the sum, not from GPU alone.
    soc_energy_joules: float = 0.0
    soc_power_watts: float = 0.0

    # Which rail set the derived per-token/per-watt numbers should come from:
    # "soc" on Apple Silicon, "gpu" on discrete-GPU hosts. Recorded so
    # downstream aggregation repeats this monitor's choice instead of
    # guessing. Empty on samples produced before this field existed.
    basis: str = ""


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
        """Return the measurement method.

        One of ``hw_counter``, ``polling``, ``rapl``, ``ioreport``, or
        ``tdp_estimate``. Everything but the last is a real measurement;
        ``tdp_estimate`` is modelled and only reachable when the caller
        explicitly opts in.
        """

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
    allow_estimates: bool = False,
) -> Optional[EnergyMonitor]:
    """Factory — auto-detect and return the best available EnergyMonitor.

    Detection order: NVIDIA > AMD > Apple > CPU RAPL.
    If *prefer_vendor* is set, try that vendor first.

    Every monitor returned by the normal path reports *measured* energy. When
    *allow_estimates* is set and nothing measurable is present, a modelled
    estimator may be returned instead — currently only on Apple Silicon, and
    only when the IOReport backend is missing. Estimators always report a
    distinct ``energy_method`` so callers can tell modelled joules from
    measured ones. Off by default: a fabricated number that lands in the
    telemetry DB is indistinguishable from a real one at query time.

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

    if allow_estimates:
        try:
            from openjarvis.telemetry.energy_apple import AppleEnergyMonitor

            if AppleEnergyMonitor.estimate_available():
                logger.warning(
                    "No measurable energy backend found; falling back to a "
                    "modelled Apple Silicon estimate. Install "
                    "`openjarvis[energy-apple]` for real measurements."
                )
                return AppleEnergyMonitor(
                    poll_interval_ms=poll_interval_ms,
                    allow_estimates=True,
                )
        except Exception as exc:
            logger.debug("Energy estimate fallback unavailable: %s", exc)

    return None


__all__ = [
    "BASIS_GPU",
    "BASIS_SOC",
    "EnergyMonitor",
    "EnergySample",
    "EnergyVendor",
    "create_energy_monitor",
]
