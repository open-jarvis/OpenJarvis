"""FeedbackCollector -- aggregates feedback from multiple sources."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from openjarvis.core.types import Trace
from openjarvis.learning.optimize.feedback.judge import TraceJudge


class FeedbackCollector:
    """Collects feedback signals: explicit user scores + LLM judge evaluations.

    Signals are stored in-memory as dicts with at least ``trace_id``,
    ``score``, ``source``, and ``timestamp`` keys.
    """

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_explicit(
        self,
        trace_id: str,
        score: float,
        source: str = "api",
    ) -> None:
        """Record an explicit numeric score (0-1) for a trace."""
        self._records.append(
            {
                "trace_id": trace_id,
                "score": min(max(score, 0.0), 1.0),
                "source": source,
                "timestamp": time.time(),
            }
        )

    def record_thumbs(self, trace_id: str, thumbs_up: bool) -> None:
        """Record a thumbs-up / thumbs-down signal (converted to 1.0/0.0)."""
        self._records.append(
            {
                "trace_id": trace_id,
                "score": 1.0 if thumbs_up else 0.0,
                "source": "thumbs",
                "timestamp": time.time(),
            }
        )

    # ------------------------------------------------------------------
    # Judge-driven evaluation
    # ------------------------------------------------------------------

    def evaluate_traces(
        self,
        traces: List[Trace],
        judge: TraceJudge,
    ) -> List[Dict[str, Any]]:
        """Score *traces* via the LLM judge and record the results.

        Returns the list of newly created feedback records.
        """
        new_records: List[Dict[str, Any]] = []
        for trace in traces:
            score, feedback = judge.score_trace(trace)
            record: Dict[str, Any] = {
                "trace_id": trace.trace_id,
                "score": score,
                "source": "judge",
                "feedback": feedback,
                "timestamp": time.time(),
            }
            self._records.append(record)
            new_records.append(record)
        return new_records

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_records(
        self,
        trace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return stored records, optionally filtered by *trace_id*."""
        if trace_id is None:
            return list(self._records)
        return [r for r in self._records if r["trace_id"] == trace_id]

    def stats(self) -> Dict[str, Any]:
        """Return aggregate statistics over all recorded feedback.

        Returns a dict with ``count``, ``mean_score``, and a simple
        ``distribution`` bucket (low / medium / high).
        """
        count = len(self._records)
        if count == 0:
            return {
                "count": 0,
                "mean_score": 0.0,
                "distribution": {"low": 0, "medium": 0, "high": 0},
            }

        scores = [r["score"] for r in self._records]
        mean_score = sum(scores) / count
        low = sum(1 for s in scores if s < 0.4)
        medium = sum(1 for s in scores if 0.4 <= s < 0.7)
        high = sum(1 for s in scores if s >= 0.7)

        return {
            "count": count,
            "mean_score": mean_score,
            "distribution": {"low": low, "medium": medium, "high": high},
        }


__all__ = ["FeedbackCollector"]
