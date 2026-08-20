"""Abstract base classes for scoring."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.backend import InferenceBackend
from openjarvis.evals.core.types import EvalRecord


class Scorer(ABC):
    """Base class for all scorers."""

    scorer_id: str

    @abstractmethod
    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        """Score a model answer against the reference.

        Returns (is_correct, metadata) where is_correct may be None
        if scoring could not be determined.
        """


class LLMJudgeScorer(Scorer):
    """Base for scorers that need an LLM to judge answers."""

    def __init__(self, judge_backend: InferenceBackend, judge_model: str) -> None:
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def _ask_judge(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Send a prompt to the judge LLM and return the response text."""
        return self._judge_backend.generate(
            prompt,
            model=self._judge_model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )


__all__ = ["LLMJudgeScorer", "Scorer"]
