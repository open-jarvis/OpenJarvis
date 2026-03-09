"""CPU RAPL energy monitor — reads Intel/AMD RAPL counters from sysfs."""

from __future__ import annotations

import logging
import platform
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator, List, Tuple

from openjarvis.telemetry.energy_monitor import (
    EnergyMonitor,
    EnergySample,
    EnergyVendor,
)

logger = logging.getLogger(__name__)

_RAPL_BASE = Path("/sys/class/powercap/intel-rapl")


class RaplDomain:
    """A single RAPL power domain (e.g., intel-rapl:0, intel-rapl:0:0)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = self._read_name()
        self.max_energy_uj = self._read_max_energy()

    def _read_name(self) -> str:
        name_file = self.path / "name"
        try:
            return name_file.read_text().strip()
        except (OSError, PermissionError) as exc:
            logger.debug("Failed to read RAPL domain name: %s", exc)
            return self.path.name

    def _read_max_energy(self) -> int:
        max_file = self.path / "max_energy_range_uj"
        try:
            return int(max_file.read_text().strip())
        except (OSError, PermissionError, ValueError) as exc:
            logger.debug("Failed to read RAPL max energy: %s", exc)
            return 0

    def read_energy_uj(self) -> int:
        """Read the current energy counter value in microjoules."""
        energy_file = self.path / "energy_uj"
        try:
            return int(energy_file.read_text().strip())
        except (OSError, PermissionError, ValueError) as exc:
            logger.debug("Failed to read RAPL energy: %s", exc)
            return 0


def _discover_domains(base: Path = _RAPL_BASE) -> List[RaplDomain]:
    """Discover all RAPL domains under the sysfs powercap tree."""
    domains: List[RaplDomain] = []
    if not base.is_dir():
        return domains

    # Find top-level intel-rapl:N directories
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and entry.name.startswith("intel-rapl:"):
            energy_file = entry / "energy_uj"
            if energy_file.exists():
                domains.append(RaplDomain(entry))

            # Check for sub-domains (e.g., intel-rapl:0:0 for dram)
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and sub.name.startswith("intel-rapl:"):
                    sub_energy = sub / "energy_uj"
                    if sub_energy.exists():
                        domains.append(RaplDomain(sub))

    return domains


class RaplEnergyMonitor(EnergyMonitor):
    """CPU energy monitor reading Intel RAPL counters from sysfs.

    No external dependencies — reads directly from
    ``/sys/class/powercap/intel-rapl/``.  Handles counter wrap-around
    using ``max_energy_range_uj``.
    """

    def __init__(
        self,
        poll_interval_ms: int = 50,
        rapl_base: Path = _RAPL_BASE,
    ) -> None:
        self._poll_interval_ms = poll_interval_ms
        self._rapl_base = rapl_base
        self._domains: List[RaplDomain] = []
        self._initialized = False

        if platform.system() == "Linux":
            try:
                self._domains = _discover_domains(rapl_base)
                self._initialized = len(self._domains) > 0
            except Exception as exc:
                logger.debug("RAPL monitor initialization failed: %s", exc)
                self._initialized = False

    @staticmethod
    def available() -> bool:
        if platform.system() != "Linux":
            return False
        return _RAPL_BASE.is_dir() and len(_discover_domains()) > 0

    def vendor(self) -> EnergyVendor:
        return EnergyVendor.CPU_RAPL

    def energy_method(self) -> str:
        return "rapl"

    def _read_all(self) -> Dict[str, Tuple[int, int]]:
        """Read (energy_uj, max_energy_uj) for all domains, keyed by name."""
        readings: Dict[str, Tuple[int, int]] = {}
        for domain in self._domains:
            readings[domain.name] = (
                domain.read_energy_uj(),
                domain.max_energy_uj,
            )
        return readings

    @staticmethod
    def _compute_delta(
        start: Dict[str, Tuple[int, int]],
        end: Dict[str, Tuple[int, int]],
    ) -> Dict[str, float]:
        """Compute energy delta in microjoules, handling wrap-around."""
        deltas: Dict[str, float] = {}
        for name, (end_uj, max_uj) in end.items():
            start_uj, _ = start.get(name, (0, 0))
            if end_uj >= start_uj:
                delta = end_uj - start_uj
            else:
                # Counter wrapped around
                delta = (max_uj - start_uj) + end_uj if max_uj > 0 else 0
            deltas[name] = float(delta)
        return deltas

    @contextmanager
    def sample(self) -> Generator[EnergySample, None, None]:
        result = EnergySample(
            vendor=EnergyVendor.CPU_RAPL.value,
            device_name="CPU (RAPL)",
            device_count=len(self._domains),
            energy_method=self.energy_method(),
        )

        if not self._initialized:
            t_start = time.monotonic()
            yield result
            result.duration_seconds = time.monotonic() - t_start
            return

        start_readings = self._read_all()
        t_start = time.monotonic()

        yield result

        wall = time.monotonic() - t_start
        end_readings = self._read_all()

        deltas_uj = self._compute_delta(start_readings, end_readings)

        # Categorize domains into CPU, DRAM, etc.
        cpu_uj = 0.0
        dram_uj = 0.0
        total_uj = 0.0

        for name, delta in deltas_uj.items():
            lower_name = name.lower()
            if "dram" in lower_name:
                dram_uj += delta
            elif "package" in lower_name or "core" in lower_name:
                cpu_uj += delta
            else:
                cpu_uj += delta  # Default: count as CPU
            total_uj += delta

        result.energy_joules = total_uj / 1e6
        result.cpu_energy_joules = cpu_uj / 1e6
        result.dram_energy_joules = dram_uj / 1e6
        result.duration_seconds = wall
        if wall > 0:
            result.mean_power_watts = result.energy_joules / wall

    def close(self) -> None:
        self._domains = []
        self._initialized = False


__all__ = ["RaplEnergyMonitor"]
