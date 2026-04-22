"""LiveResearchBench scorer — checklist-based LLM-as-judge scoring.

For each task, LiveResearchBench provides a list of checklist items that a
good response must cover. The scorer asks an LLM judge to evaluate each
checklist item against the response, producing a per-item pass/fail.
Final score = fraction of passed items (coverage).

Reference: https://arxiv.org/abs/2510.14240
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

# Tasks with coverage >= PASS_THRESHOLD are marked as correct
PASS_THRESHOLD = 0.5


def _build_judge_prompt(
    *,
    question: str,
    answer: str,
    checklist: List[str],
) -> str:
    """Build a batched judge prompt that evaluates all checklist items at once."""
    bullets = "\n".join(f"{i}. {item}" for i, item in enumerate(checklist, 1))
    return f"""You are an expert evaluator scoring a deep-research report against a checklist.

## Research Question
{question}

## Checklist Items
{bullets}

## Report to Evaluate
{answer}

## Instructions
For each checklist item above, decide whether the report adequately covers it.
A checklist item is COVERED if the report includes the required information or
analysis in a clear, accurate, and substantive way. A checklist item is NOT
COVERED if the report omits it, addresses it only superficially, or contains
incorrect information.

Return your evaluation as JSON with this exact structure:
```json
{{
  "judgments": [
    {{"index": 1, "covered": true, "reason": "brief justification"}},
    {{"index": 2, "covered": false, "reason": "brief justification"}}
  ]
}}
```

Return one judgment per checklist item, indexed in the same order as above.
Be rigorous: `covered: true` only if the report genuinely satisfies the item."""


def _parse_judge_response(raw: str, num_items: int) -> List[Dict[str, Any]]:
    """Extract per-item judgments from the judge's raw response.

    Returns one dict per checklist item ({index, covered, reason}). Missing
    items default to ``covered=False``.
    """
    if not raw or not raw.strip():
        return [
            {"index": i + 1, "covered": False, "reason": "empty judge response"}
            for i in range(num_items)
        ]

    judgments: Dict[int, Dict[str, Any]] = {}

    # Collect JSON candidates: code blocks first, then balanced braces.
    candidates: List[str] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL):
        candidates.append(match.group(1))

    depth = 0
    current: List[str] = []
    for char in raw:
        if char == "{":
            if depth == 0:
                current = []
            depth += 1
        if depth > 0:
            current.append(char)
        if char == "}":
            depth -= 1
            if depth == 0 and current:
                candidates.append("".join(current))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        items = parsed.get("judgments") or parsed.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                idx_int = int(item.get("index"))
            except (ValueError, TypeError):
                continue
            covered_raw = item.get("covered")
            if isinstance(covered_raw, bool):
                covered = covered_raw
            elif isinstance(covered_raw, str):
                covered = covered_raw.strip().lower() in {
                    "true",
                    "yes",
                    "covered",
                    "1",
                    "y",
                }
            else:
                covered = False
            judgments[idx_int] = {
                "index": idx_int,
                "covered": covered,
                "reason": str(item.get("reason", "")),
            }
        if judgments:
            break

    if not judgments:
        LOGGER.warning("Failed to parse judge response — marking all items uncovered")

    # Fill gaps with covered=False so downstream code always sees N items.
    return [
        judgments.get(
            i + 1,
            {
                "index": i + 1,
                "covered": False,
                "reason": "missing from judge output",
            },
        )
        for i in range(num_items)
    ]


class LiveResearchBenchScorer(LLMJudgeScorer):
    """Checklist-based LLM-as-judge scorer for LiveResearchBench.

    For each sample, the judge evaluates each checklist item against the
    model's report. Score = fraction covered. Tasks with score >=
    ``PASS_THRESHOLD`` (default 0.5) are marked correct.
    """

    scorer_id = "liveresearchbench"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        checklist: List[str] = list(record.metadata.get("checklist", []) or [])

        if not model_answer or not model_answer.strip():
            return False, {
                "score": 0.0,
                "coverage": 0.0,
                "covered_count": 0,
                "checklist_size": len(checklist),
                "reason": "empty_response",
            }

        if not checklist:
            LOGGER.warning(
                "No checklist attached to %s — scoring cannot produce a coverage number",
                record.record_id,
            )
            return None, {
                "score": 0.0,
                "coverage": 0.0,
                "covered_count": 0,
                "checklist_size": 0,
                "reason": "no_checklist",
            }

        question = record.metadata.get("question") or record.problem

        prompt = _build_judge_prompt(
            question=question,
            answer=model_answer,
            checklist=checklist,
        )

        try:
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=4096)
        except Exception as exc:
            LOGGER.error("LLM judge call failed for %s: %s", record.record_id, exc)
            return None, {
                "score": 0.0,
                "error": str(exc),
                "checklist_size": len(checklist),
            }

        judgments = _parse_judge_response(raw, num_items=len(checklist))
        covered_count = sum(1 for j in judgments if j["covered"])
        coverage = covered_count / len(checklist)
        is_correct = coverage >= PASS_THRESHOLD

        metadata: Dict[str, Any] = {
            "score": coverage,
            "coverage": coverage,
            "covered_count": covered_count,
            "checklist_size": len(checklist),
            "judgments": judgments,
            "raw_judge_output": raw,
        }
        return is_correct, metadata


__all__ = ["LiveResearchBenchScorer"]
