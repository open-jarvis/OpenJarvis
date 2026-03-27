"""Research mining scorer — LLM judge for research synthesis quality.

Evaluates accuracy, depth, source quality, and synthesis of
AI-generated research responses.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are evaluating an AI-generated research response.

The AI was asked to research a topic and provide key findings, supporting evidence, and a synthesis.

Expected key facts/topics that should be covered:
{key_facts}

Research question:
{question}

AI response:
{response}

Evaluate the response on these criteria:
1. Accuracy: Are the stated facts correct and not hallucinated?
2. Coverage: Does it address the key facts/topics listed above?
3. Depth: Does it go beyond surface-level observations?
4. Structure: Is it well-organized with clear findings and synthesis?
5. Relevance: Does it stay focused on the research question?

Your response MUST use exactly this format:
accuracy: <1-5>
coverage: <1-5>
depth: <1-5>
structure: <1-5>
relevance: <1-5>
reasoning: <brief explanation>
overall_correct: <yes or no>"""


class ResearchMiningScorer(LLMJudgeScorer):
    """Score research mining responses on quality dimensions."""

    scorer_id = "research_mining"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        # Extract original question from the prompt
        question = (
            record.problem.split("Research question: ")[-1].split("\n")[0].strip()
        )

        try:
            prompt = _JUDGE_PROMPT.format(
                key_facts=record.reference,
                question=question,
                response=model_answer,
            )
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=512)

            scores = {}
            for dim in ("accuracy", "coverage", "depth", "structure", "relevance"):
                match = re.search(
                    rf"^{dim}:\s*(\d)",
                    raw,
                    re.MULTILINE | re.IGNORECASE,
                )
                scores[dim] = int(match.group(1)) if match else 3

            overall_match = re.search(
                r"^overall_correct:\s*(yes|no)",
                raw,
                re.MULTILINE | re.IGNORECASE,
            )

            avg_score = sum(scores.values()) / len(scores)
            if overall_match:
                is_correct = overall_match.group(1).lower() == "yes"
            else:
                is_correct = avg_score >= 3.5

            return is_correct, {
                "match_type": "llm_judge",
                "scores": scores,
                "avg_score": avg_score,
                "raw_judge_output": raw,
            }
        except Exception as exc:
            LOGGER.error("Research mining LLM judge failed: %s", exc)
            return None, {
                "match_type": "llm_judge_error",
                "error": str(exc),
            }


__all__ = ["ResearchMiningScorer"]
