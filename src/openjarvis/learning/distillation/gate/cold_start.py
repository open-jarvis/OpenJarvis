"""Cold start detection and bootstrap for the distillation subsystem.

Day one: no traces, no benchmark. The system must not crash and must
give the user a clear message about what's needed. This module provides
readiness checks and the bootstrap logic.

See spec §13.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReadinessResult:
    """Result of a readiness check."""

    ready: bool
    message: str
    trace_count: int = 0
    high_feedback_count: int = 0


def check_readiness(
    trace_store: Any,
    min_traces: int = 20,
) -> ReadinessResult:
    """Check if there are enough traces to run a learning session.

    Parameters
    ----------
    trace_store :
        TraceStore instance.
    min_traces :
        Minimum total trace count required.

    Returns
    -------
    ReadinessResult
        ``ready`` is True if there are enough traces.
    """
    count = trace_store.count()
    if count < min_traces:
        return ReadinessResult(
            ready=False,
            message=(
                f"Not enough traces yet to learn from. "
                f"Have {count}, need at least {min_traces}. "
                f"Use OpenJarvis for a while and try again."
            ),
            trace_count=count,
        )
    return ReadinessResult(
        ready=True,
        message=f"Ready: {count} traces available.",
        trace_count=count,
    )


def check_benchmark_ready(
    trace_store: Any,
    min_feedback: float = 0.7,
    min_samples: int = 10,
) -> ReadinessResult:
    """Check if there are enough high-feedback traces for a benchmark.

    The bootstrap benchmark needs at least ``min_samples`` traces with
    feedback >= ``min_feedback``.

    Parameters
    ----------
    trace_store :
        TraceStore instance.
    min_feedback :
        Minimum feedback score for benchmark-quality traces.
    min_samples :
        Minimum number of high-feedback traces needed.
    """
    # Query traces with high feedback
    traces = trace_store.list_traces(limit=min_samples * 2)
    high_feedback = [
        t
        for t in traces
        if getattr(t, "feedback", None) is not None and t.feedback >= min_feedback
    ]
    count = len(high_feedback)

    if count < min_samples:
        return ReadinessResult(
            ready=False,
            message=(
                f"Personal benchmark needs at least {min_samples} "
                f"high-feedback traces (feedback >= {min_feedback}). "
                f"Have {count} so far. Will be populated automatically."
            ),
            trace_count=trace_store.count(),
            high_feedback_count=count,
        )
    return ReadinessResult(
        ready=True,
        message=f"Benchmark ready: {count} high-feedback traces available.",
        trace_count=trace_store.count(),
        high_feedback_count=count,
    )
