"""Throughput benchmark — measures tokens per second with per-sample stats."""

from __future__ import annotations

import logging
import time
from typing import Any, List

from openjarvis.bench._stats import compute_stats
from openjarvis.bench._stubs import BaseBenchmark, BenchmarkResult
from openjarvis.core.registry import BenchmarkRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

_PROMPT = "Write a short paragraph about artificial intelligence."


class ThroughputBenchmark(BaseBenchmark):
    """Measures inference throughput in tokens per second."""

    @property
    def name(self) -> str:
        return "throughput"

    @property
    def description(self) -> str:
        return "Measures inference throughput in tokens per second"

    def run(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        num_samples: int = 10,
        warmup_samples: int = 0,
        **kwargs: Any,
    ) -> BenchmarkResult:
        messages = [Message(role=Role.USER, content=_PROMPT)]

        for _ in range(warmup_samples):
            try:
                engine.generate(messages, model=model)
            except Exception as exc:
                logger.debug("Warmup request failed: %s", exc)

        per_sample_tps: List[float] = []
        per_sample_tokens: List[float] = []
        per_sample_latency: List[float] = []
        errors = 0

        for _ in range(num_samples):
            t0 = time.time()
            try:
                result = engine.generate(messages, model=model)
                elapsed = time.time() - t0
                usage = result.get("usage", {})
                tokens = usage.get("completion_tokens", 0)

                tps = tokens / elapsed if elapsed > 0 else 0.0
                per_sample_tps.append(tps)
                per_sample_tokens.append(float(tokens))
                per_sample_latency.append(elapsed)
            except Exception as exc:
                logger.debug("Measurement request failed: %s", exc)
                errors += 1

        total_tokens = sum(per_sample_tokens)
        total_time = sum(per_sample_latency)

        metrics: dict[str, float] = {}
        metrics.update(compute_stats("tokens_per_second", per_sample_tps))
        metrics.update(compute_stats("latency_seconds", per_sample_latency))
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
        )


def ensure_registered() -> None:
    """Register the throughput benchmark if not already present."""
    if not BenchmarkRegistry.contains("throughput"):
        BenchmarkRegistry.register_value("throughput", ThroughputBenchmark)


__all__ = ["ThroughputBenchmark"]
