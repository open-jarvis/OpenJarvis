"""Energy benchmark — per-sample energy, power, and efficiency measurement."""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from openjarvis.bench._stats import compute_stats
from openjarvis.bench._stubs import BaseBenchmark, BenchmarkResult
from openjarvis.core.registry import BenchmarkRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

_PROMPT = "Write a short paragraph about artificial intelligence."


class EnergyBenchmark(BaseBenchmark):
    """Measures energy per token at thermal equilibrium.

    Collects per-sample energy (J), power (W), throughput (tok/s), and
    energy-per-token (J/tok) so the stats table has real p50/min/max/std/p95
    values rather than just aggregates.
    """

    @property
    def name(self) -> str:
        return "energy"

    @property
    def description(self) -> str:
        return "Measures energy per token at thermal equilibrium"

    def run(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        num_samples: int = 10,
        warmup_samples: int = 5,
        energy_monitor: Optional[Any] = None,
        **kwargs: Any,
    ) -> BenchmarkResult:
        messages = [Message(role=Role.USER, content=_PROMPT)]

        for _ in range(warmup_samples):
            try:
                engine.generate(messages, model=model)
            except Exception as exc:
                logger.debug("Warmup request failed: %s", exc)

        per_energy_j: List[float] = []
        per_power_w: List[float] = []
        per_tps: List[float] = []
        per_ept: List[float] = []  # energy per token
        per_latency: List[float] = []
        per_tokens: List[float] = []
        errors = 0
        energy_method = ""

        if energy_monitor is not None:
            from openjarvis.telemetry.steady_state import SteadyStateDetector

            detector = SteadyStateDetector()
            energy_method = getattr(energy_monitor, "energy_method", lambda: "")()

            for _ in range(num_samples):
                t0 = time.time()
                try:
                    with energy_monitor.sample() as sample:
                        result = engine.generate(messages, model=model)
                    elapsed = time.time() - t0

                    usage = result.get("usage", {})
                    tokens = usage.get("completion_tokens", 0)
                    energy_j = sample.energy_joules
                    power_w = energy_j / elapsed if elapsed > 0 else 0.0
                    tps = tokens / elapsed if elapsed > 0 else 0.0
                    ept = energy_j / tokens if tokens > 0 else 0.0

                    per_energy_j.append(energy_j)
                    per_power_w.append(power_w)
                    per_tps.append(tps)
                    per_ept.append(ept)
                    per_latency.append(elapsed)
                    per_tokens.append(float(tokens))

                    detector.record(tps)
                except Exception as exc:
                    logger.debug("Measurement request failed: %s", exc)
                    errors += 1

            ss_result = detector.result
        else:
            for _ in range(num_samples):
                t0 = time.time()
                try:
                    result = engine.generate(messages, model=model)
                    elapsed = time.time() - t0

                    usage = result.get("usage", {})
                    tokens = usage.get("completion_tokens", 0)
                    tps = tokens / elapsed if elapsed > 0 else 0.0

                    per_tps.append(tps)
                    per_latency.append(elapsed)
                    per_tokens.append(float(tokens))
                except Exception as exc:
                    logger.debug("Measurement request failed: %s", exc)
                    errors += 1
            ss_result = None

        total_tokens = sum(per_tokens)
        total_time = sum(per_latency)
        total_energy = sum(per_energy_j)

        metrics: dict[str, float] = {}
        metrics.update(compute_stats("tokens_per_second", per_tps))
        metrics.update(compute_stats("power_watts", per_power_w))
        metrics.update(compute_stats("energy_joules", per_energy_j))
        metrics.update(compute_stats("energy_per_token_j", per_ept))
        metrics.update(compute_stats("latency_seconds", per_latency))
        metrics["total_energy_joules"] = total_energy
        metrics["total_tokens"] = total_tokens
        metrics["total_time_seconds"] = total_time

        metadata: dict[str, Any] = {}
        if engine.engine_id == "apple_fm":
            metadata["token_estimation"] = (
                "~4 chars/token (Apple FM SDK does not expose counts)"
            )

        return BenchmarkResult(
            benchmark_name=self.name,
            model=model,
            engine=engine.engine_id,
            metrics=metrics,
            metadata=metadata,
            samples=num_samples,
            errors=errors,
            warmup_samples=warmup_samples,
            steady_state_samples=(ss_result.steady_state_samples if ss_result else 0),
            steady_state_reached=(
                ss_result.steady_state_reached if ss_result else False
            ),
            total_energy_joules=total_energy,
            energy_per_token_joules=(
                total_energy / total_tokens if total_tokens > 0 else 0.0
            ),
            energy_method=energy_method,
        )


def ensure_registered() -> None:
    """Register the energy benchmark if not already present."""
    if not BenchmarkRegistry.contains("energy"):
        BenchmarkRegistry.register_value("energy", EnergyBenchmark)


__all__ = ["EnergyBenchmark"]
