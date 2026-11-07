"""Benchmarking framework for FridayAI inference engines."""

from __future__ import annotations

from friday_ai.bench._stubs import BaseBenchmark, BenchmarkResult, BenchmarkSuite
from friday_ai.core.registry import BenchmarkRegistry


def ensure_registered() -> None:
    """Ensure all benchmark implementations are registered."""
    from friday_ai.bench.energy import ensure_registered as _reg_energy
    from friday_ai.bench.latency import ensure_registered as _reg_latency
    from friday_ai.bench.throughput import ensure_registered as _reg_throughput

    _reg_latency()
    _reg_throughput()
    _reg_energy()


# Trigger registration on import
ensure_registered()

__all__ = [
    "BaseBenchmark",
    "BenchmarkRegistry",
    "BenchmarkResult",
    "BenchmarkSuite",
    "ensure_registered",
]
