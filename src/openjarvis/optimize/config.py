"""TOML config loader for optimization runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

from openjarvis.optimize.types import ObjectiveSpec

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
    from openjarvis.optimize.types import DEFAULT_OBJECTIVES

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


__all__ = ["load_objectives", "load_optimize_config"]
