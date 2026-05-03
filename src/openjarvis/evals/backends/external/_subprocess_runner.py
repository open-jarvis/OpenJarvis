"""Shared one-shot subprocess invocation with energy/timing capture.

Used by HermesBackend and OpenClawBackend to spawn their respective
foreign-framework runner scripts. Hermetic: a fresh subprocess per task,
energy sampled by NVML/powermetrics/ROCm-SMI/RAPL fallback chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
