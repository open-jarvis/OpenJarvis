"""Per-cluster regression detection for the benchmark gate.

After an edit is applied, the gate compares the before and after
BenchmarkSnapshots. If any cluster's score dropped by more than
``max_regression``, the edit is rejected.

See spec §7.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openjarvis.learning.spec_search.models import BenchmarkSnapshot


@dataclass
class RegressionResult:
    """Result of a regression check."""

    has_regression: bool
    regressed_clusters: dict[str, float] = field(default_factory=dict)
    """Cluster id → negative delta for clusters that regressed beyond threshold."""


def regression_check(
    before: BenchmarkSnapshot,
    after: BenchmarkSnapshot,
    max_regression: float = 0.05,
) -> RegressionResult:
    """Check if any cluster regressed beyond the threshold.

    Parameters
    ----------
    before :
        Benchmark snapshot before the edit.
    after :
        Benchmark snapshot after the edit.
    max_regression :
        Maximum allowed per-cluster score drop (default 0.05).

    Returns
    -------
    RegressionResult
        ``has_regression`` is True if any cluster dropped more than
        ``max_regression``. ``regressed_clusters`` maps cluster ids
        to their negative deltas.
    """
    regressed: dict[str, float] = {}

    for cluster_id, before_score in before.cluster_scores.items():
        after_score = after.cluster_scores.get(cluster_id, 0.0)
        delta = after_score - before_score
        if delta < -max_regression:
            regressed[cluster_id] = delta

    return RegressionResult(
        has_regression=bool(regressed),
        regressed_clusters=regressed,
    )
