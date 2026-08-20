"""BenchmarkGate: accept or reject edits based on benchmark performance.

Runs the personal benchmark via a provided scorer callable, compares
before/after snapshots, and decides accept/reject based on thresholds.

See spec §7.3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from openjarvis.learning.spec_search.gate.regression import regression_check
from openjarvis.learning.spec_search.models import BenchmarkSnapshot

logger = logging.getLogger(__name__)

# Type for the scorer callable: takes benchmark_version, subsample_size,
# seed and returns a BenchmarkSnapshot.
ScorerFn = Callable[..., BenchmarkSnapshot]


@dataclass
class GateResult:
    """Result of a benchmark gate evaluation."""

    accepted: bool
    snapshot: BenchmarkSnapshot
    delta: float
    reason: str = ""


class BenchmarkGate:
    """Runs the personal benchmark and decides accept/reject.

    Parameters
    ----------
    scorer :
        Callable that runs the benchmark and returns a BenchmarkSnapshot.
        Signature: ``(benchmark_version, subsample_size, seed) -> BenchmarkSnapshot``.
    benchmark_version :
        Which benchmark version to score against (locked per session).
    min_improvement :
        Minimum overall score improvement to accept (default 0.0).
    max_regression :
        Maximum per-cluster score drop before rejecting (default 0.05).
    subsample_size :
        Number of tasks to score per gate run (default 50).
    """

    def __init__(
        self,
        *,
        scorer: ScorerFn,
        benchmark_version: str,
        min_improvement: float = 0.0,
        max_regression: float = 0.05,
        subsample_size: int = 50,
    ) -> None:
        self._scorer = scorer
        self._benchmark_version = benchmark_version
        self._min_improvement = min_improvement
        self._max_regression = max_regression
        self._subsample_size = subsample_size

    def evaluate(
        self,
        *,
        before: BenchmarkSnapshot,
        session_seed: int,
    ) -> GateResult:
        """Run the benchmark and compare against the before snapshot.

        Parameters
        ----------
        before :
            Snapshot captured before the edit was applied.
        session_seed :
            Deterministic seed for subsampling (same across all gate
            runs in one session).

        Returns
        -------
        GateResult
            ``accepted`` is True if the edit should be committed.
        """
        after = self._scorer(
            benchmark_version=self._benchmark_version,
            subsample_size=self._subsample_size,
            seed=session_seed,
        )

        delta = after.overall_score - before.overall_score

        # Check regression
        reg = regression_check(before, after, max_regression=self._max_regression)
        if reg.has_regression:
            clusters_str = ", ".join(
                f"{cid}: {d:+.3f}" for cid, d in reg.regressed_clusters.items()
            )
            reason = f"regression in clusters: {clusters_str}"
            logger.info("Gate rejected: %s", reason)
            return GateResult(
                accepted=False,
                snapshot=after,
                delta=delta,
                reason=reason,
            )

        # Check improvement
        if delta <= self._min_improvement:
            reason = (
                f"no improvement: delta={delta:.4f}, "
                f"min_improvement={self._min_improvement}"
            )
            logger.info("Gate rejected: %s", reason)
            return GateResult(
                accepted=False,
                snapshot=after,
                delta=delta,
                reason=reason,
            )

        logger.info("Gate accepted: delta=%.4f", delta)
        return GateResult(
            accepted=True,
            snapshot=after,
            delta=delta,
        )
