"""Apple Silicon energy monitor — per-rail IOReport counters via zeus-apple-silicon.

Reads the SoC's own energy counters (CPU, GPU, DRAM, Apple Neural Engine)
through ``zeus_apple_silicon``, a nanobind extension over IOReport. No root
required, unlike ``powermetrics``.

**Why not via ``zeus-ml``:** zeus wraps this same library as
``zeus.device.soc.apple.AppleSilicon``, but that module landed on zeus master
in April 2025 and no zeus release has shipped since February 2025 — every
published ``zeus-ml`` (through 0.11.0.post1) has no ``zeus.device.soc``
package at all, and no ``apple`` extra. Depending on the underlying library
directly is the only spelling that actually resolves.

The ANE rail is what makes this worth doing: Apple Foundation Models runs
predominantly on the Neural Engine, so a GPU-only reading makes it look
almost free.
"""

from __future__ import annotations

import atexit
import logging
import platform
import subprocess
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator, Optional

from openjarvis.telemetry.energy_monitor import (
    BASIS_SOC,
    EnergyMonitor,
    EnergySample,
    EnergyVendor,
)

logger = logging.getLogger(__name__)

try:
    from zeus_apple_silicon import AppleEnergyMonitor as _AppleRailReader

    _NATIVE_AVAILABLE = True
except ImportError:
    _AppleRailReader = None  # type: ignore[assignment]
    _NATIVE_AVAILABLE = False


# Monitors holding a live native handle. Long-lived callers (`jarvis serve`)
# create one for the process lifetime and never close it, which leaves the
# nanobind object alive when the extension's types are torn down -- the
# extension then prints "leaked instance" warnings on exit. Releasing the
# handles at interpreter shutdown keeps that teardown clean.
_LIVE_MONITORS: "weakref.WeakSet[AppleEnergyMonitor]" = weakref.WeakSet()


@atexit.register
def _release_live_monitors() -> None:  # pragma: no cover - shutdown hook
    for monitor in list(_LIVE_MONITORS):
        try:
            monitor.close()
        except Exception:
            pass


# Typical package TDP (watts) by chip family.  Used only for the opt-in
# modelled estimate, never for measured readings.
_CHIP_TDP: dict[str, float] = {
    "M1": 15.0,
    "M1 Pro": 30.0,
    "M1 Max": 60.0,
    "M1 Ultra": 90.0,
    "M2": 15.0,
    "M2 Pro": 30.0,
    "M2 Max": 60.0,
    "M2 Ultra": 90.0,
    "M3": 15.0,
    "M3 Pro": 30.0,
    "M3 Max": 60.0,
    "M3 Ultra": 90.0,
    "M4": 15.0,
    "M4 Pro": 30.0,
    "M4 Max": 60.0,
    "M5": 15.0,
    "M5 Pro": 30.0,
    "M5 Max": 60.0,
    "M5 Ultra": 90.0,
}


def _detect_chip() -> tuple[str, float]:
    """Return (chip_name, tdp_watts) for the current Apple Silicon SoC.

    ``platform.processor()`` reports a bare "arm" on every Apple Silicon Mac,
    so ``sysctl`` is the only way to name the actual part.
    """
    try:
        r = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        brand = r.stdout.strip()
    except Exception as exc:
        logger.debug("Failed to detect Apple Silicon chip brand: %s", exc)
        brand = ""

    for chip, tdp in sorted(_CHIP_TDP.items(), key=lambda kv: -len(kv[0])):
        if chip in brand:
            return brand or chip, tdp

    return brand or "Apple Silicon", 20.0


@dataclass
class _Rails:
    """One reading of the SoC's energy rails, in joules.

    A rail is ``None`` when this chip does not expose that counter — which is
    not the same as zero, and must not be summed as if it were.
    """

    cpu: Optional[float] = None
    gpu: Optional[float] = None
    dram: Optional[float] = None
    ane: Optional[float] = None

    @property
    def total(self) -> float:
        """Sum of the rails that are actually present."""
        rails = (self.cpu, self.gpu, self.dram, self.ane)
        return sum(v for v in rails if v is not None)

    def __sub__(self, other: "_Rails") -> "_Rails":
        def diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
            if a is None or b is None:
                return None
            # Counters are monotonic; a negative delta means a wrapped or
            # reset counter, which is better reported as "unknown" than as a
            # negative energy.
            return a - b if a >= b else None

        return _Rails(
            cpu=diff(self.cpu, other.cpu),
            gpu=diff(self.gpu, other.gpu),
            dram=diff(self.dram, other.dram),
            ane=diff(self.ane, other.ane),
        )


def _mj(value: Any) -> Optional[float]:
    """Convert one millijoule counter to joules, or ``None`` if absent."""
    if value is None:
        return None
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


def _rails_from_metrics(metrics: Any) -> _Rails:
    """Map a ``zeus_apple_silicon.AppleEnergyMetrics`` onto :class:`_Rails`.

    ``cpu_total_mj`` already subsumes the per-core, per-cluster and
    core-manager breakdowns the object also exposes (verified on an M1 Pro:
    the cluster fields sum to ``cpu_total_mj``), so adding those would double
    count. ``gpu_sram_mj`` is a separate rail from ``gpu_mj`` and does need
    adding.
    """
    gpu = _mj(getattr(metrics, "gpu_mj", None))
    gpu_sram = _mj(getattr(metrics, "gpu_sram_mj", None))
    if gpu is not None and gpu_sram is not None:
        gpu = gpu + gpu_sram
    elif gpu is None:
        gpu = gpu_sram

    return _Rails(
        cpu=_mj(getattr(metrics, "cpu_total_mj", None)),
        gpu=gpu,
        dram=_mj(getattr(metrics, "dram_mj", None)),
        ane=_mj(getattr(metrics, "ane_mj", None)),
    )


class AppleEnergyMonitor(EnergyMonitor):
    """Apple Silicon energy monitor.

    Measures CPU, GPU, DRAM and ANE rails via ``zeus-apple-silicon``. When
    that backend is absent, :meth:`available` reports ``False`` so the factory
    falls through rather than inventing numbers; a modelled TDP estimate is
    reachable only by explicitly constructing with ``allow_estimates=True``.
    """

    def __init__(
        self,
        poll_interval_ms: int = 50,
        allow_estimates: bool = False,
    ) -> None:
        self._poll_interval_ms = poll_interval_ms
        self._allow_estimates = allow_estimates
        self._reader: Any = None
        self._chip_name, self._tdp_watts = _detect_chip()
        # Previous cumulative reading, for deriving power in snapshot().
        self._prev: Optional[tuple[float, _Rails]] = None

        if _NATIVE_AVAILABLE and platform.system() == "Darwin":
            try:
                self._reader = _AppleRailReader()
                _LIVE_MONITORS.add(self)
            except Exception as exc:
                logger.debug(
                    "Failed to initialize Apple Silicon energy monitor: %s",
                    exc,
                )

    # ---- capability probes ---------------------------------------------

    @staticmethod
    def available() -> bool:
        """True only when rails can actually be *measured*.

        Deliberately stricter than "is this a Mac": returning True on any
        Apple Silicon host is what previously let a modelled estimate
        masquerade as a measurement for every reader downstream.
        """
        if not AppleEnergyMonitor.estimate_available():
            return False
        if not _NATIVE_AVAILABLE:
            return False
        try:
            _AppleRailReader()
        except Exception as exc:
            logger.debug("Apple Silicon energy backend unusable: %s", exc)
            return False
        return True

    @staticmethod
    def estimate_available() -> bool:
        """True on any Apple Silicon host, measurable or not."""
        return platform.system() == "Darwin" and platform.machine() == "arm64"

    def vendor(self) -> EnergyVendor:
        return EnergyVendor.APPLE

    def energy_method(self) -> str:
        return "ioreport" if self._reader is not None else "tdp_estimate"

    # ---- measurement ----------------------------------------------------

    def _new_sample(self) -> EnergySample:
        return EnergySample(
            vendor=EnergyVendor.APPLE.value,
            device_name=self._chip_name,
            device_count=1,
            energy_method=self.energy_method(),
            basis=BASIS_SOC,
        )

    @contextmanager
    def sample(self) -> Generator[EnergySample, None, None]:
        result = self._new_sample()

        if self._reader is not None:
            yield from self._sample_ioreport(result)
        elif self._allow_estimates:
            yield from self._sample_estimate(result)
        else:
            # No backend and no opt-in: hand back an empty sample rather than
            # a fabricated one. Callers see zeros and energy_method tells them
            # why.
            yield result

    def _sample_ioreport(
        self,
        result: EnergySample,
    ) -> Generator[EnergySample, None, None]:
        assert self._reader is not None
        window = f"openjarvis_{time.monotonic_ns()}"
        t_start = time.monotonic()
        self._reader.begin_window(window)

        try:
            yield result
        finally:
            # No `return` in this block: returning from a finally discards an
            # exception the body raised, so a failed end_window would swallow
            # the caller's error.
            try:
                metrics = self._reader.end_window(window)
            except Exception as exc:
                logger.debug("Apple energy window failed to close: %s", exc)
            else:
                self._apply(
                    result,
                    _rails_from_metrics(metrics),
                    time.monotonic() - t_start,
                )

    @staticmethod
    def _apply(result: EnergySample, rails: _Rails, wall: float) -> None:
        """Write a rail reading and its derived totals onto *result*."""
        result.cpu_energy_joules = rails.cpu or 0.0
        result.gpu_energy_joules = rails.gpu or 0.0
        result.dram_energy_joules = rails.dram or 0.0
        result.ane_energy_joules = rails.ane or 0.0

        total = rails.total
        result.soc_energy_joules = total
        # On Apple Silicon the SoC sum *is* the energy figure — every rail
        # here is on the same package.
        result.energy_joules = total
        result.duration_seconds = wall
        if wall > 0:
            result.mean_power_watts = total / wall
            result.soc_power_watts = total / wall
            result.cpu_power_watts = (rails.cpu or 0.0) / wall
            result.gpu_power_watts = (rails.gpu or 0.0) / wall
            result.ane_power_watts = (rails.ane or 0.0) / wall

    def snapshot(self) -> EnergySample:
        """Instantaneous reading, for background polling by ``TelemetrySession``.

        Energy fields carry the *cumulative* since-boot counters, which is what
        the eval runners difference across a window
        (``_compute_energy_delta`` takes last-minus-first). Power is derived
        from the delta against the previous snapshot, so the first call in a
        session reports zero watts.
        """
        result = self._new_sample()
        if self._reader is None:
            return result

        try:
            metrics = self._reader.get_cumulative_energy()
        except Exception as exc:
            logger.debug("Apple cumulative energy read failed: %s", exc)
            return result

        now = time.monotonic()
        rails = _rails_from_metrics(metrics)

        result.cpu_energy_joules = rails.cpu or 0.0
        result.gpu_energy_joules = rails.gpu or 0.0
        result.dram_energy_joules = rails.dram or 0.0
        result.ane_energy_joules = rails.ane or 0.0
        result.soc_energy_joules = rails.total
        result.energy_joules = rails.total
        result.num_snapshots = 1

        prev = self._prev
        self._prev = (now, rails)
        if prev is not None:
            dt = now - prev[0]
            if dt > 0:
                delta = rails - prev[1]
                result.duration_seconds = dt
                result.cpu_power_watts = (delta.cpu or 0.0) / dt
                result.gpu_power_watts = (delta.gpu or 0.0) / dt
                result.ane_power_watts = (delta.ane or 0.0) / dt
                result.soc_power_watts = delta.total / dt
                result.mean_power_watts = result.soc_power_watts

        return result

    # ---- opt-in modelled estimate --------------------------------------

    def _sample_estimate(
        self,
        result: EnergySample,
    ) -> Generator[EnergySample, None, None]:
        """Model energy as wall-clock × TDP, split by fixed rail ratios.

        This is not a measurement. It reads no counters and no utilization: a
        ten-second sleep and a ten-second generation produce identical joules,
        and the rail split is four constants. It exists only so a host without
        ``zeus-apple-silicon`` can produce order-of-magnitude figures when the
        caller has explicitly asked for estimates, and it always reports
        ``energy_method="tdp_estimate"`` so those figures stay separable from
        real ones.
        """
        _ACTIVE_RATIO = 0.60
        t0 = time.monotonic()

        try:
            yield result
        finally:
            # No `return` in this block -- see _sample_ioreport.
            wall = time.monotonic() - t0
            if wall <= 0:
                result.duration_seconds = 0.0
            else:
                power_w = self._tdp_watts * _ACTIVE_RATIO
                energy_j = power_w * wall
                rails = _Rails(
                    cpu=energy_j * 0.25,
                    gpu=energy_j * 0.55,
                    dram=energy_j * 0.15,
                    ane=energy_j * 0.05,
                )
                self._apply(result, rails, wall)

    def close(self) -> None:
        self._reader = None
        self._prev = None
        _LIVE_MONITORS.discard(self)


__all__ = ["AppleEnergyMonitor"]
