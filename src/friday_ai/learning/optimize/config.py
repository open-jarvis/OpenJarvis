"""TOML config loader for optimization runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

from friday_ai.learning.optimize.types import ObjectiveSpec

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def load_optimize_config(path: Union[str, Path]) -> Dict[str, Any]:
    """Load an optimization config TOML file.

    Returns the raw dict with keys such as ``optimize.max_trials``,
    ``optimize.benchmark``, ``optimize.search``, ``optimize.fixed``,
    ``optimize.constraints``, etc.

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Optimization config not found: {path}")

    with open(path, "rb") as fh:
        data: Dict[str, Any] = tomllib.load(fh)

    return data


def load_objectives(data: Dict[str, Any]) -> List[ObjectiveSpec]:
    """Extract objectives from a loaded optimization config.

    Reads ``optimize.objectives`` (a list of tables) and returns
    a list of :class:`ObjectiveSpec`.  Falls back to
    :data:`DEFAULT_OBJECTIVES` if the key is absent.
    """
    from friday_ai.learning.optimize.types import DEFAULT_OBJECTIVES

    optimize = data.get("optimize", {})
    raw_objectives = optimize.get("objectives")
    if not raw_objectives:
        return list(DEFAULT_OBJECTIVES)

    result: List[ObjectiveSpec] = []
    for obj in raw_objectives:
        result.append(
            ObjectiveSpec(
                metric=obj["metric"],
                direction=obj.get("direction", "maximize"),
                weight=obj.get("weight", 1.0),
            )
        )
    return result


def load_benchmark_specs(data: Dict[str, Any]) -> List[Any]:
    """Extract benchmark specs from a loaded optimization config.

    Supports two formats:
    - Multi-benchmark: ``[[optimize.benchmarks]]`` array of tables
    - Single-benchmark fallback: ``optimize.benchmark`` string

    Returns a list of :class:`BenchmarkSpec` (from trial_runner).
    Returns an empty list if no benchmarks are configured (caller
    should fall back to CLI --benchmark).
    """
    from friday_ai.learning.optimize.trial_runner import BenchmarkSpec

    optimize = data.get("optimize", {})

    # Multi-benchmark format: [[optimize.benchmarks]]
    raw_benchmarks = optimize.get("benchmarks")
    if raw_benchmarks and isinstance(raw_benchmarks, list):
        # Check if it's a list of dicts (table array) vs list of strings
        if raw_benchmarks and isinstance(raw_benchmarks[0], dict):
            specs: List[BenchmarkSpec] = []
            for entry in raw_benchmarks:
                specs.append(
                    BenchmarkSpec(
                        benchmark=entry.get("name", entry.get("benchmark", "")),
                        max_samples=entry.get("max_samples", 200),
                        weight=entry.get("weight", 1.0),
                    )
                )
            return specs

    # Single-benchmark fallback
    single = optimize.get("benchmark", "")
    if single:
        max_samples = optimize.get("max_samples", 50)
        return [BenchmarkSpec(benchmark=single, max_samples=max_samples)]

    return []


__all__ = ["load_benchmark_specs", "load_objectives", "load_optimize_config"]
