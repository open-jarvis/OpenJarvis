"""Morning brief scorer — LLM judge for briefing quality.

Evaluates completeness, prioritization, conciseness, and actionability
of generated morning briefings.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are evaluating an AI-generated morning briefing.

The AI was given calendar events, todos, news topics, and pending messages, and asked to produce a prioritized morning brief.

Key priorities that should be highlighted:
{key_priorities}

Original user context (summary):
{problem_excerpt}

AI-generated briefing:
{response}

Evaluate the briefing on these criteria:
1. Completeness: Does it cover calendar, todos, messages, and news?
2. Prioritization: Are the most urgent/important items highlighted first?
3. Conciseness: Is it well-organized and scannable, not too verbose?
4. Actionability: Does it clearly indicate what needs attention today?
5. Key priorities: Does it mention the key priorities listed above?

Your response MUST use exactly this format:
completeness: <1-5>
prioritization: <1-5>
conciseness: <1-5>
actionability: <1-5>
key_priorities_covered: <yes or partial or no>
reasoning: <brief explanation>
overall_correct: <yes or no>"""


class MorningBriefScorer(LLMJudgeScorer):
    """Score morning briefings on quality dimensions."""

    scorer_id = "morning_brief"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        # Truncate problem for the judge prompt to save tokens
        problem_excerpt = (
            record.problem[:500] + "..."
            if len(record.problem) > 500
            else record.problem
        )

        try:
            prompt = _JUDGE_PROMPT.format(
                key_priorities=record.reference,
                problem_excerpt=problem_excerpt,
                response=model_answer,
            )
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=512)

            # Extract scores
            scores = {}
            for dim in (
                "completeness",
                "prioritization",
                "conciseness",
                "actionability",
            ):
                match = re.search(
                    rf"^{dim}:\s*(\d)",
                    raw,
                    re.MULTILINE | re.IGNORECASE,
                )
                scores[dim] = int(match.group(1)) if match else 3

            priorities_match = re.search(
                r"^key_priorities_covered:\s*(yes|partial|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )
            priorities_covered = (
                priorities_match.group(1).lower() if priorities_match else "partial"
            )

            overall_match = re.search(
                r"^overall_correct:\s*(yes|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )

            # Consider correct if average score >= 3.5 and priorities at least partial
            avg_score = sum(scores.values()) / len(scores)
            if overall_match:
                is_correct = overall_match.group(1).lower() == "yes"
            else:
                is_correct = avg_score >= 3.5 and priorities_covered != "no"

            return is_correct, {
                "match_type": "llm_judge",
                "scores": scores,
                "avg_score": avg_score,
                "key_priorities_covered": priorities_covered,
                "raw_judge_output": raw,
            }
        except Exception as exc:
            LOGGER.error("Morning brief LLM judge failed: %s", exc)
            return None, {
                "match_type": "llm_judge_error",
                "error": str(exc),
            }


__all__ = ["MorningBriefScorer"]
