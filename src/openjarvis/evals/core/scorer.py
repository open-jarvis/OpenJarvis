"""Abstract base classes for scoring."""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.backend import InferenceBackend
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

# Transient failures worth retrying the judge call on. A single rate-limit
# (429) used to fall straight through to `llm_fallback_error` and score the
# sample WRONG — e.g. 93/100 GAIA judge calls 429'd on one run and zeroed the
# whole bench. Retry with exponential backoff so a busy judge endpoint doesn't
# get mis-scored as a wrong answer.
_JUDGE_MAX_RETRIES = 6
_JUDGE_BASE_DELAY_S = 2.0
_JUDGE_MAX_DELAY_S = 60.0
_RETRYABLE_MARKERS = (
    "429",
    "rate_limit",
    "rate limit",
    "overloaded",
    "timeout",
    "timed out",
    "503",
    "502",
    "500",
    "connection",
    "temporarily unavailable",
)


def _is_retryable_judge_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _RETRYABLE_MARKERS)


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
        """Send a prompt to the judge LLM and return the response text.

        Retries transient failures (429 / rate-limit / 5xx / timeout) with
        exponential backoff + jitter so a busy judge endpoint doesn't get
        mis-scored as a wrong answer. Non-retryable errors, or exhaustion of
        the retry budget, re-raise to the caller (which records the failure).
        """
        last_exc: Optional[Exception] = None
        for attempt in range(_JUDGE_MAX_RETRIES):
            try:
                return self._judge_backend.generate(
                    prompt,
                    model=self._judge_model,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001 - re-raised below
                last_exc = exc
                if attempt == _JUDGE_MAX_RETRIES - 1 or not _is_retryable_judge_error(
                    exc
                ):
                    raise
                delay = min(_JUDGE_BASE_DELAY_S * (2**attempt), _JUDGE_MAX_DELAY_S)
                delay += random.uniform(0.0, delay * 0.25)  # jitter
                LOGGER.warning(
                    "judge call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1,
                    _JUDGE_MAX_RETRIES,
                    exc,
                    delay,
                )
                time.sleep(delay)
        # Unreachable (loop either returns or raises), but keeps type-checkers happy.
        raise last_exc  # type: ignore[misc]


__all__ = ["LLMJudgeScorer", "Scorer"]
