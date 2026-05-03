"""Shared one-shot subprocess invocation with energy/timing capture.

Used by HermesBackend and OpenClawBackend to spawn their respective
foreign-framework runner scripts. Hermetic: a fresh subprocess per task,
energy sampled by NVML/powermetrics/ROCm-SMI/RAPL fallback chain.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

LOGGER = logging.getLogger(__name__)

_GRACE_PERIOD_SECONDS = 30.0


@dataclass(slots=True)
class EnergySample:
    """One sample from the energy sampler thread."""

    timestamp: float  # seconds since sampler start
    watts: float


@dataclass(slots=True)
class SubprocessResult:
    """Result of a one-shot subprocess invocation."""

    stdout: str
    stderr: str
    exit_code: int
    latency_seconds: float
    energy_joules: Optional[float]
    peak_power_w: Optional[float]
    sampler_method: str  # "nvml" | "powermetrics" | "rocm_smi" | "rapl" | "unavailable"
    parsed_json: Dict[str, Any] = field(default_factory=dict)
    samples: List[EnergySample] = field(default_factory=list)
    # "subprocess_crash" | "timeout" | "malformed_runner_output" | ...
    error: Optional[str] = None


class _RunnerOutput(BaseModel):
    """Schema the foreign-framework runner scripts must emit."""

    content: str
    usage: Dict[str, int] = Field(default_factory=dict)
    trajectory: List[Dict[str, Any]] = Field(default_factory=list)
    tool_calls: int = 0
    turn_count: int = 0
    error: Optional[str] = None


def run_one_shot(
    cmd: List[str],
    env: Mapping[str, str],
    timeout: float,
    output_json_path: Path,
) -> SubprocessResult:
    """Spawn cmd as a one-shot subprocess; capture stdout, energy, JSON output.

    The subprocess is expected to write its result as JSON matching
    ``_RunnerOutput`` to ``output_json_path`` before exiting. Energy is
    sampled at 10 Hz over the process's lifetime via the fallback sampler
    chain (NVML -> powermetrics -> ROCm-SMI -> RAPL -> unavailable).

    Returns a ``SubprocessResult`` with structured ``error`` field on
    failure; never raises for subprocess crashes (those are signal, not
    exceptions).
    """
    sampler = _start_sampler()
    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as e:
        sampler.stop()
        return SubprocessResult(
            stdout="",
            stderr=str(e),
            exit_code=-1,
            latency_seconds=0.0,
            energy_joules=None,
            peak_power_w=None,
            sampler_method=sampler.method,
            error="subprocess_crash",
        )

    error: Optional[str] = None
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=_GRACE_PERIOD_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        error = "timeout"

    elapsed = time.monotonic() - t0
    samples = sampler.stop()
    energy_j, peak_w = _integrate_energy(samples, elapsed)

    if error is None and proc.returncode != 0:
        error = "subprocess_crash"

    parsed: Dict[str, Any] = {}
    if error is None:
        if not output_json_path.exists():
            error = "invalid_runner_output"
        else:
            try:
                raw = json.loads(output_json_path.read_text())
                _RunnerOutput.model_validate(raw)  # validate shape
                parsed = raw
            except json.JSONDecodeError:
                error = "malformed_runner_output"
            except ValidationError as e:
                LOGGER.error("runner_output_validation_failed: %s", e)
                error = "invalid_runner_output"

    return SubprocessResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=proc.returncode,
        latency_seconds=elapsed,
        energy_joules=energy_j,
        peak_power_w=peak_w,
        sampler_method=sampler.method,
        parsed_json=parsed,
        samples=samples,
        error=error,
    )


_SAMPLE_HZ = 10.0
_SAMPLE_INTERVAL = 1.0 / _SAMPLE_HZ


class _Sampler:
    """Base class for energy samplers running on a background thread."""

    method: str = "unavailable"

    def __init__(self) -> None:
        self._samples: List[EnergySample] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0 = time.monotonic()

    def _read_watts(self) -> float:  # pragma: no cover (subclass override)
        raise NotImplementedError

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                w = self._read_watts()
                self._samples.append(
                    EnergySample(timestamp=time.monotonic() - self._t0, watts=w)
                )
            except Exception as e:  # never crash the sampler
                LOGGER.debug("sampler_read_failed: %s", e)
            self._stop_event.wait(_SAMPLE_INTERVAL)

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> List[EnergySample]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        return list(self._samples)


class _NullSampler(_Sampler):
    method = "unavailable"

    def start(self) -> None:
        pass  # nothing to do

    def stop(self) -> List[EnergySample]:
        return []


def _try_start_nvml() -> Optional[_Sampler]:
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)

        class _NvmlSampler(_Sampler):
            method = "nvml"

            def _read_watts(self) -> float:
                return pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0

        s = _NvmlSampler()
        s.start()
        return s
    except Exception as e:
        LOGGER.debug("nvml_unavailable: %s", e)
        return None


def _try_start_powermetrics() -> Optional[_Sampler]:
    """macOS only - requires sudo or appropriate plist permissions."""
    if shutil.which("powermetrics") is None:
        return None
    # NOTE: real powermetrics integration is non-trivial (parse XML over stdout).
    # Apple-hardware support is a follow-up; documented in CHANGELOG.
    return None


def _try_start_rocm_smi() -> Optional[_Sampler]:
    if shutil.which("rocm-smi") is None:
        return None

    class _RocmSampler(_Sampler):
        method = "rocm_smi"

        def _read_watts(self) -> float:
            out = subprocess.run(
                ["rocm-smi", "--showpower", "--csv"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            # Parse "card0,15.5W" style; first number after a comma
            for line in out.splitlines():
                parts = [p.strip() for p in line.split(",")]
                for p in parts[1:]:
                    if "W" in p:
                        return float(p.replace("W", ""))
            return 0.0

    s = _RocmSampler()
    s.start()
    return s


def _try_start_rapl() -> Optional[_Sampler]:
    rapl_path = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
    if not rapl_path.exists():
        return None

    class _RaplSampler(_Sampler):
        method = "rapl"

        def __init__(self) -> None:
            super().__init__()
            self._last_uj = int(rapl_path.read_text().strip())
            self._last_t = time.monotonic()

        def _read_watts(self) -> float:
            now_uj = int(rapl_path.read_text().strip())
            now_t = time.monotonic()
            d_uj = now_uj - self._last_uj
            d_t = now_t - self._last_t
            self._last_uj = now_uj
            self._last_t = now_t
            return (d_uj * 1e-6) / d_t if d_t > 0 else 0.0

    s = _RaplSampler()
    s.start()
    return s


def _start_sampler() -> _Sampler:
    """Return a started sampler from the fallback chain, or the null sampler."""
    for try_fn in (
        _try_start_nvml,
        _try_start_powermetrics,
        _try_start_rocm_smi,
        _try_start_rapl,
    ):
        s = try_fn()
        if s is not None:
            return s
    return _NullSampler()


def _integrate_energy(
    samples: List[EnergySample], elapsed: float
) -> Tuple[Optional[float], Optional[float]]:
    """Trapezoidal-rule integration over sampled wattage to Joules."""
    if not samples:
        return None, None
    if len(samples) == 1:
        return samples[0].watts * elapsed, samples[0].watts
    energy = 0.0
    peak = 0.0
    for a, b in zip(samples, samples[1:]):
        dt = b.timestamp - a.timestamp
        avg_w = (a.watts + b.watts) / 2.0
        energy += avg_w * dt
        peak = max(peak, a.watts, b.watts)
    return energy, peak
