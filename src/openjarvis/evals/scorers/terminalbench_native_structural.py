"""TerminalBench Native scorer — test-result-based evaluation.

Reads ``is_resolved`` and ``test_results`` from the record's metadata
(populated by the native terminal-bench harness) and returns a
deterministic pass/fail without any LLM judging.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord


class TerminalBenchNativeScorer(Scorer):
    """Test-result-based scorer for TerminalBench Native tasks.

    The native terminal-bench package produces ``is_resolved`` and
    ``test_results`` fields after executing a task.  This scorer reads
    those fields from ``record.metadata`` and translates them into the
    standard ``(is_correct, meta)`` tuple.
    """

    scorer_id = "terminalbench-native"

    def __init__(
        self,
        judge_backend: object = None,
        judge_model: str = "",
    ) -> None:
        # Accept judge_backend/judge_model so the CLI factory pattern works,
        # but they are unused — scoring is based on test results.
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        meta = record.metadata

        is_resolved = meta.get("is_resolved")
        test_results = meta.get("test_results")

        # If neither field is present, we cannot determine correctness.
        if is_resolved is None and test_results is None:
            return None, {"reason": "no_test_results"}

        # Build informative metadata from available test output.
        result_meta: Dict[str, Any] = {}
        if test_results is not None:
            result_meta["test_results"] = test_results

        # Determine pass/fail
        if is_resolved is not None:
            is_correct = bool(is_resolved)
            result_meta["is_resolved"] = is_resolved
            return is_correct, result_meta

        # Fallback: if only test_results is present, treat as indeterminate.
        return None, {
            "reason": "is_resolved_missing",
            "test_results": test_results,
        }


__all__ = ["TerminalBenchNativeScorer"]
