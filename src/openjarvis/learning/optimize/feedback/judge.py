"""TraceJudge -- LLM-as-judge scoring for agent traces."""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

from openjarvis.core.types import Trace
from openjarvis.evals.core.backend import InferenceBackend

LOGGER = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an expert evaluator of AI assistant traces. "
    "You will be shown a user query, the steps the assistant took, "
    "and its final result. Rate the overall quality of the response "
    "on a scale from 0.0 (completely wrong / unhelpful) to 1.0 "
    "(perfect). Provide your score on the first line as a decimal "
    "number, then explain your reasoning."
)

_SCORE_RE = re.compile(
    r"(?:Score|Rating|Quality)?\s*[:=]?\s*(\d+(?:\.\d+)?)"
    r"(?:\s*/\s*(\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)


def _format_trace(trace: Trace) -> str:
    """Render a Trace into a textual prompt for the judge."""
    lines: List[str] = []
    lines.append(f"## Query\n{trace.query}")
    if trace.steps:
        lines.append("\n## Steps")
        for i, step in enumerate(trace.steps, 1):
            step_input = step.input.get("content", str(step.input))
            step_output = step.output.get("content", str(step.output))
            lines.append(
                f"{i}. [{step.step_type.value}] "
                f"input={step_input!r}  output={step_output!r}  "
                f"({step.duration_seconds:.3f}s)",
            )
    lines.append(f"\n## Final Result\n{trace.result}")
    return "\n".join(lines)


def _parse_score(text: str) -> float:
    """Extract a 0-1 score from the judge response.

    Handles formats like ``0.85``, ``Score: 0.85``, ``Rating: 7/10``.
    Falls back to 0.5 when parsing fails.
    """
    match = _SCORE_RE.search(text)
    if match is None:
        LOGGER.warning("Could not parse score from judge response; defaulting to 0.5")
        return 0.5

    numerator = float(match.group(1))
    denominator_str = match.group(2)

    if denominator_str is not None:
        denominator = float(denominator_str)
        if denominator > 0:
            return min(max(numerator / denominator, 0.0), 1.0)
        return 0.5

    # If the number is > 1.0 assume it is on a 0-10 scale
    if numerator > 1.0:
        return min(numerator / 10.0, 1.0)

    return min(max(numerator, 0.0), 1.0)


class TraceJudge:
    """LLM-as-judge for scoring traces when no ground truth exists.

    Given a :class:`Trace`, the judge constructs a prompt showing the
    query, agent steps, and final result, then asks an LLM to rate the
    quality on a 0-1 scale.
    """

    def __init__(self, backend: InferenceBackend, model: str) -> None:
        self._backend = backend
        self._model = model

    def score_trace(self, trace: Trace) -> Tuple[float, str]:
        """Score a single trace.

        Returns:
            ``(score, feedback)`` where *score* is in [0, 1] and
            *feedback* is the judge's textual reasoning.
        """
        prompt = _format_trace(trace)
        response = self._backend.generate(
            prompt,
            model=self._model,
            system=_SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=1024,
        )
        score = _parse_score(response)
        return score, response

    def batch_evaluate(
        self,
        traces: List[Trace],
    ) -> List[Tuple[float, str]]:
        """Evaluate multiple traces sequentially.

        Returns a list of ``(score, feedback)`` tuples, one per trace.
        """
        results: List[Tuple[float, str]] = []
        for trace in traces:
            results.append(self.score_trace(trace))
        return results


__all__ = ["TraceJudge"]
