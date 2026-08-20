"""Batch-level energy accounting — group requests and compute per-token energy."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, List, Optional


@dataclass
class BatchMetrics:
    """Aggregated metrics for a batch of inference requests."""

    batch_id: str = ""
    total_requests: int = 0
    total_tokens: int = 0
    total_energy_joules: float = 0.0
    energy_per_token_joules: float = 0.0
    energy_per_request_joules: float = 0.0
    mean_power_watts: float = 0.0
    mean_throughput_tok_per_sec: float = 0.0
    prefill_energy_joules: float = 0.0
    decode_energy_joules: float = 0.0
    per_request_energy: List[float] = field(default_factory=list)


class EnergyBatch:
    """Group inference requests into a batch and compute per-token energy.

    Works with or without an ``EnergyMonitor``.  When no monitor is provided,
    request counts are still tracked but energy values stay at zero.
    """

    def __init__(
        self,
        energy_monitor: Optional[Any] = None,
        batch_id: Optional[str] = None,
    ) -> None:
        self._monitor = energy_monitor
        self.batch_id = batch_id or str(uuid.uuid4())
        self.metrics: Optional[BatchMetrics] = None

    @contextmanager
    def sample(self) -> Generator[_BatchContext, None, None]:
        """Wrap an energy monitor sample and provide a context for recording requests.

        Yields a ``_BatchContext`` whose ``record_request()`` method should be
        called once per inference request inside the block.
        """
        ctx = _BatchContext()

        if self._monitor is not None:
            with self._monitor.sample() as energy_sample:
                start = time.monotonic()
                yield ctx
                elapsed = time.monotonic() - start
            total_energy = energy_sample.energy_joules
            mean_power = energy_sample.mean_power_watts
        else:
            start = time.monotonic()
            yield ctx
            elapsed = time.monotonic() - start
            total_energy = ctx._total_energy
            mean_power = 0.0

        total_tokens = ctx._total_tokens
        total_requests = ctx._total_requests
        per_request_energy = list(ctx._per_request_energy)

        energy_per_token = total_energy / total_tokens if total_tokens > 0 else 0.0
        energy_per_request = (
            total_energy / total_requests if total_requests > 0 else 0.0
        )
        mean_throughput = total_tokens / elapsed if elapsed > 0 else 0.0

        self.metrics = BatchMetrics(
            batch_id=self.batch_id,
            total_requests=total_requests,
            total_tokens=total_tokens,
            total_energy_joules=total_energy,
            energy_per_token_joules=energy_per_token,
            energy_per_request_joules=energy_per_request,
            mean_power_watts=mean_power,
            mean_throughput_tok_per_sec=mean_throughput,
            per_request_energy=per_request_energy,
        )


class _BatchContext:
    """Accumulator for per-request stats within an ``EnergyBatch.sample()`` block."""

    def __init__(self) -> None:
        self._total_tokens: int = 0
        self._total_requests: int = 0
        self._total_energy: float = 0.0
        self._per_request_energy: List[float] = []

    def record_request(
        self,
        tokens: int,
        prompt_tokens: int = 0,
        energy_joules: float = 0.0,
    ) -> None:
        """Record one inference request in this batch.

        Parameters
        ----------
        tokens:
            Total tokens (prompt + completion) for this request.
        prompt_tokens:
            Prompt tokens (informational; included in *tokens*).
        energy_joules:
            Per-request energy if known (e.g. from per-request metering).
        """
        self._total_tokens += tokens
        self._total_requests += 1
        self._total_energy += energy_joules
        self._per_request_energy.append(energy_joules)


__all__ = [
    "BatchMetrics",
    "EnergyBatch",
]
