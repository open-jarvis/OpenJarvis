"""GPU energy collector for hybrid cell runs.

Samples ``pynvml.nvmlDeviceGetPowerUsage`` at ~2Hz on a background thread,
integrates power × dt → joules across the cell's wall-time. Used as a
context manager wrapping ``_run_cell_locked`` so the whole cell's GPU
energy is attributed to the cell (not per-task — concurrency makes
per-task attribution very noisy).

Failure modes are absorbed: if NVML isn't available (no GPU on this host,
container without ``libnvidia-ml.so.1``, permission denied) the collector
logs *once* and returns ``0.0``. It must never crash the run.

Scope notes
-----------
* Samples **all visible NVIDIA GPUs on the host where the runner runs**.
  In our setup that's the L40S node that also hosts vLLM
  (``mkt1`` / ``matx2``), so this captures the local-model serving GPUs.
  If the runner is invoked from a host without GPUs (e.g. a login node
  with vLLM on a remote box), the collector logs and yields 0 — set
  ``OPENJARVIS_HYBRID_ENERGY=0`` to silence the warning.
* ``CUDA_VISIBLE_DEVICES`` is *honored* for parity with vLLM: only those
  GPU indices are sampled. Unset = all GPUs on the host.
* **Cloud energy is not measured** — cloud calls go over HTTPS to
  Anthropic/OpenAI/Google, no measurable joules on our side. A future
  pass could add a per-token J/token estimate (e.g. Patterson et al.
  2021, Luccioni et al. 2022) but those numbers are vendor-opaque and
  uncertain — leaving as a TODO until we explicitly decide to estimate.
"""

from __future__ import annotations

import os
import threading
import time
from typing import List, Optional

_NVML_WARNED = False


def _log_once(msg: str) -> None:
    global _NVML_WARNED
    if not _NVML_WARNED:
        print(f"[energy] {msg}", flush=True)
        _NVML_WARNED = True


def _resolve_gpu_indices(total: int) -> List[int]:
    """Honor CUDA_VISIBLE_DEVICES; default to every visible GPU."""
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES")
    if not cvd:
        return list(range(total))
    out: List[int] = []
    for s in cvd.split(","):
        s = s.strip()
        if not s:
            continue
        try:
            idx = int(s)
        except ValueError:
            continue
        if 0 <= idx < total:
            out.append(idx)
    return out or list(range(total))


class EnergyCollector:
    """Background NVML power sampler integrating to joules.

    Use as a context manager::

        with EnergyCollector() as ec:
            ...                       # run the cell
        joules = ec.energy_j_total    # also available after __exit__

    Safe to instantiate even when NVML is unavailable: ``energy_j_total``
    will simply be ``0.0`` and a one-time warning will be printed.
    """

    def __init__(self, sample_hz: float = 2.0) -> None:
        self.sample_hz = float(sample_hz)
        self.energy_j_total: float = 0.0
        self.samples: int = 0
        self.gpu_indices: List[int] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0: float = 0.0
        self._t1: float = 0.0
        self._enabled = os.environ.get("OPENJARVIS_HYBRID_ENERGY", "1") != "0"
        self._pynvml = None
        self._handles: list = []

    # ---- context manager
    def __enter__(self) -> "EnergyCollector":
        self._t0 = time.time()
        if not self._enabled:
            return self
        try:
            import pynvml  # type: ignore[import-not-found]
            pynvml.nvmlInit()
            total = pynvml.nvmlDeviceGetCount()
            self.gpu_indices = _resolve_gpu_indices(total)
            self._handles = [
                pynvml.nvmlDeviceGetHandleByIndex(i) for i in self.gpu_indices
            ]
            # Probe once so we fail fast if power query is unsupported.
            for h in self._handles:
                pynvml.nvmlDeviceGetPowerUsage(h)
            self._pynvml = pynvml
        except Exception as e:  # noqa: BLE001 — NVML failures must never crash the run
            _log_once(
                f"NVML unavailable ({type(e).__name__}: {e}); "
                "energy_j_total will be 0. Set OPENJARVIS_HYBRID_ENERGY=0 to silence."
            )
            self._pynvml = None
            return self

        self._thread = threading.Thread(
            target=self._sample_loop, name="energy-sampler", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._t1 = time.time()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        if self._pynvml is not None:
            try:
                self._pynvml.nvmlShutdown()
            except Exception:  # noqa: BLE001
                pass

    # ---- sampler thread
    def _sample_loop(self) -> None:
        """Trapezoid-integrate Σ_gpu power_W × dt over the cell run.

        ``nvmlDeviceGetPowerUsage`` returns milliwatts. Sample interval
        is best-effort (~``1/sample_hz`` s); if the host is overloaded
        and a tick lands late we still use the real ``dt`` so the
        integral stays honest. Trapezoid rule (mean of consecutive
        readings) damps jitter vs. left-Riemann.
        """
        pynvml = self._pynvml
        assert pynvml is not None
        period = 1.0 / max(self.sample_hz, 0.1)
        last_t = time.time()
        last_total_w: Optional[float] = None
        while not self._stop.is_set():
            try:
                total_mw = 0
                for h in self._handles:
                    total_mw += pynvml.nvmlDeviceGetPowerUsage(h)
                total_w = total_mw / 1000.0
            except Exception:  # noqa: BLE001 — keep going even on transient NVML errors
                self._stop.wait(period)
                continue
            now = time.time()
            if last_total_w is not None:
                dt = now - last_t
                # Trapezoid rule: mean power across the interval × dt.
                self.energy_j_total += 0.5 * (total_w + last_total_w) * dt
            last_t = now
            last_total_w = total_w
            self.samples += 1
            self._stop.wait(period)

    # ---- inspection
    @property
    def wall_s(self) -> float:
        return max(self._t1 - self._t0, 0.0) if self._t1 else (time.time() - self._t0)


__all__ = ["EnergyCollector"]
