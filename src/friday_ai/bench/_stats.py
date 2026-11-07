"""Shared statistics helpers for benchmark per-sample metrics."""

from __future__ import annotations

import statistics
from typing import Dict, List


def _percentile(data: List[float], p: float) -> float:
    """Compute the p-th percentile via linear interpolation."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def compute_stats(name: str, values: List[float]) -> Dict[str, float]:
    """Compute mean/p50/p95/min/max/std for a list of per-sample values.

    Returns dict with keys like ``mean_{name}``, ``p50_{name}``, etc.
    Returns empty dict if *values* is empty.
    """
    if not values:
        return {}
    return {
        f"mean_{name}": statistics.mean(values),
        f"p50_{name}": statistics.median(values),
        f"p95_{name}": _percentile(values, 0.95),
        f"min_{name}": min(values),
        f"max_{name}": max(values),
        f"std_{name}": statistics.stdev(values) if len(values) > 1 else 0.0,
    }
