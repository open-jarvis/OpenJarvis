"""Steady-state detection for energy measurement at thermal equilibrium."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List


@dataclass
class SteadyStateConfig:
    """Configuration for steady-state detection."""

    warmup_samples: int = 5
    window_size: int = 5
    cv_threshold: float = 0.05
    min_steady_samples: int = 3
    metric: str = "throughput"


@dataclass
class SteadyStateResult:
    """Result of steady-state detection."""

    total_samples: int = 0
    warmup_samples: int = 0
    steady_state_samples: int = 0
    steady_state_reached: bool = False
    warmup_throughputs: List[float] = field(default_factory=list)
    warmup_energies: List[float] = field(default_factory=list)
    steady_throughputs: List[float] = field(default_factory=list)
    steady_energies: List[float] = field(default_factory=list)


class SteadyStateDetector:
    """Detect steady state using coefficient of variation over a sliding window.

    The first ``warmup_samples`` recordings are always classified as warmup.
    After warmup, the CV (stdev / mean) of the last ``window_size`` values is
    checked.  When CV < ``cv_threshold`` for ``min_steady_samples`` consecutive
    checks, steady state is declared.
    """

    def __init__(self, config: SteadyStateConfig | None = None) -> None:
        self._config = config or SteadyStateConfig()
        self._throughputs: List[float] = []
        self._energies: List[float] = []
        self._consecutive_stable: int = 0
        self._steady_state_reached: bool = False

    def record(
        self,
        throughput: float,
        energy: float = 0.0,
        latency: float = 0.0,
    ) -> bool:
        """Record a sample.  Returns ``True`` when steady state is reached."""
        self._throughputs.append(throughput)
        self._energies.append(energy)

        cfg = self._config

        # Still in warmup phase
        if len(self._throughputs) <= cfg.warmup_samples:
            return False

        # Already declared steady
        if self._steady_state_reached:
            return True

        # Not enough post-warmup samples for a full window yet
        post_warmup = self._throughputs[cfg.warmup_samples :]
        if len(post_warmup) < cfg.window_size:
            return False

        # Compute CV over the last window_size values
        window = post_warmup[-cfg.window_size :]
        mean = statistics.mean(window)
        if mean == 0:
            self._consecutive_stable = 0
            return False

        cv = statistics.stdev(window) / mean if len(window) > 1 else 0.0

        if cv < cfg.cv_threshold:
            self._consecutive_stable += 1
        else:
            self._consecutive_stable = 0

        if self._consecutive_stable >= cfg.min_steady_samples:
            self._steady_state_reached = True
            return True

        return False

    @property
    def result(self) -> SteadyStateResult:
        """Return a snapshot of the detection state."""
        cfg = self._config
        n_warmup = min(len(self._throughputs), cfg.warmup_samples)
        warmup_t = self._throughputs[:n_warmup]
        warmup_e = self._energies[:n_warmup]
        steady_t = self._throughputs[n_warmup:]
        steady_e = self._energies[n_warmup:]

        return SteadyStateResult(
            total_samples=len(self._throughputs),
            warmup_samples=n_warmup,
            steady_state_samples=len(steady_t),
            steady_state_reached=self._steady_state_reached,
            warmup_throughputs=list(warmup_t),
            warmup_energies=list(warmup_e),
            steady_throughputs=list(steady_t),
            steady_energies=list(steady_e),
        )

    def reset(self) -> None:
        """Clear all recorded state."""
        self._throughputs.clear()
        self._energies.clear()
        self._consecutive_stable = 0
        self._steady_state_reached = False


__all__ = [
    "SteadyStateConfig",
    "SteadyStateDetector",
    "SteadyStateResult",
]
