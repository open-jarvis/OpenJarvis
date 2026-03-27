"""SWEfficiency scorer — structural patch validation.

Full SWEfficiency evaluation requires running performance benchmarks
inside the repository environment.  This scorer performs lightweight
structural checks on the model output (e.g. whether it looks like a
valid patch) and defers the authoritative pass/fail to external
benchmark execution.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord

_DIFF_MARKERS = [
    r"^---\s",
    r"^\+\+\+\s",
    r"^@@\s",
    r"^diff\s+--git\s",
]
_DIFF_RE = re.compile("|".join(_DIFF_MARKERS), re.MULTILINE)


class SWEfficiencyScorer(Scorer):
    """Structural validation scorer for SWEfficiency patches.

    Since true SWEfficiency scoring requires running performance
    benchmarks in a sandboxed repository checkout, this scorer only
    checks whether the model produced something that looks like a valid
    unified diff.  The ``is_correct`` field is set to ``None``
    (indeterminate) when a patch-like response is detected — downstream
    harnesses should measure the actual speedup.
    """

    scorer_id = "swefficiency"

    def __init__(
        self,
        judge_backend: object = None,
        judge_model: str = "",
    ) -> None:
        # Accept judge_backend/judge_model so the CLI factory pattern works,
        # but they are unused — scoring is purely structural.
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        has_diff = bool(_DIFF_RE.search(model_answer))

        if has_diff:
            return None, {
                "reason": "requires_test_execution",
                "has_diff_markers": True,
            }

        return None, {
            "reason": "requires_test_execution",
            "has_diff_markers": False,
        }


__all__ = ["SWEfficiencyScorer"]
