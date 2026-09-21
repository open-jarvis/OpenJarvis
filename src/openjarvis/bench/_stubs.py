"""ABC for benchmark implementations and the BenchmarkSuite runner."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openjarvis.engine._stubs import InferenceEngine


@dataclass(slots=True)
class BenchmarkResult:
    """Result from running a single benchmark."""

    benchmark_name: str
    model: str
    engine: str
    metrics: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    samples: int = 0
    errors: int = 0
    warmup_samples: int = 0
    steady_state_samples: int = 0
    steady_state_reached: bool = False
    total_energy_joules: float = 0.0
    energy_per_token_joules: float = 0.0
    energy_method: str = ""


def engine_info(engine: Any) -> Optional[Dict[str, Any]]:
    """Run metadata from an engine that can describe itself, or ``None``.

    Duck-typed the way IPW's runner writes ``client_info`` into
    ``summary.json``: ``describe`` is not on the ``InferenceEngine`` ABC, so
    engines opt in by defining it. The AFM engine uses this to record its SDK
    version, context size and host chip, none of which is recoverable from the
    benchmark results alone.

    The return value is validated rather than trusted. It lands in a JSONL
    file, so anything that is not a plain dict of JSON-safe scalars is
    dropped or stringified -- an engine returning something exotic must not be
    able to fail the whole benchmark write.
    """
    describe = getattr(engine, "describe", None)
    if not callable(describe):
        return None
    try:
        info = describe()
    except Exception:
        return None
    if not isinstance(info, dict):
        return None

    safe: Dict[str, Any] = {}
    for key, value in info.items():
        if not isinstance(key, str):
            continue
        if value is None or isinstance(value, (bool, int, float, str)):
            safe[key] = value
        else:
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                safe[key] = repr(value)
            else:
                safe[key] = value
    return safe or None


class BaseBenchmark(ABC):
    """Base class for all benchmark implementations.

    Subclasses must be registered via
    ``@BenchmarkRegistry.register("name")`` to become discoverable.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this benchmark."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this benchmark measures."""

    @abstractmethod
    def run(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        num_samples: int = 10,
        **kwargs: Any,
    ) -> BenchmarkResult:
        """Execute the benchmark and return results."""


class BenchmarkSuite:
    """Run a collection of benchmarks and aggregate results."""

    def __init__(self, benchmarks: Optional[List[BaseBenchmark]] = None) -> None:
        self._benchmarks = benchmarks or []

    def run_all(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        num_samples: int = 10,
        **kwargs: Any,
    ) -> List[BenchmarkResult]:
        """Run all benchmarks and return a list of results."""
        results: List[BenchmarkResult] = []
        for bench in self._benchmarks:
            result = bench.run(engine, model, num_samples=num_samples, **kwargs)
            results.append(result)
        return results

    def to_jsonl(self, results: List[BenchmarkResult]) -> str:
        """Serialize results to JSONL format (one JSON object per line)."""
        lines: List[str] = []
        for r in results:
            obj = {
                "benchmark_name": r.benchmark_name,
                "model": r.model,
                "engine": r.engine,
                "metrics": r.metrics,
                "metadata": r.metadata,
                "samples": r.samples,
                "errors": r.errors,
            }
            lines.append(json.dumps(obj))
        return "\n".join(lines)

    def summary(self, results: List[BenchmarkResult]) -> Dict[str, Any]:
        """Create a summary dict from benchmark results."""
        return {
            "benchmark_count": len(results),
            "benchmarks": [
                {
                    "name": r.benchmark_name,
                    "model": r.model,
                    "engine": r.engine,
                    "metrics": r.metrics,
                    "samples": r.samples,
                    "errors": r.errors,
                }
                for r in results
            ],
        }


__all__ = ["BaseBenchmark", "BenchmarkResult", "BenchmarkSuite"]
