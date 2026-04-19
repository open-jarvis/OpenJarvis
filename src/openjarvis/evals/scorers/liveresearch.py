"""DeepResearchBench scorer — LLM-as-judge for deep research quality.

Evaluates research output quality across four dimensions from the
DeepResearchBench rubric: comprehensiveness, insight, instruction_following,
and readability. Uses LLM-as-judge with per-task criteria when available,
falling back to a generic research quality rubric.

Reference: https://github.com/Ayanami0730/deep_research_bench
Paper: https://arxiv.org/abs/2510.14240
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

# The four scoring dimensions from DeepResearchBench
DIMENSIONS = ["comprehensiveness", "insight", "instruction_following", "readability"]

# Default dimension weights when task-specific weights are unavailable
DEFAULT_WEIGHTS = {
    "comprehensiveness": 0.25,
    "insight": 0.30,
    "instruction_following": 0.25,
    "readability": 0.20,
}

_GENERIC_RUBRIC = """Evaluate the research report across these four dimensions on a 0-10 scale:

1. **Comprehensiveness** (information coverage, depth, data support, balanced perspectives):
   - 0-3: Minimal coverage, misses major aspects of the topic
   - 4-6: Covers main points but lacks depth or misses important subtopics
   - 7-8: Thorough coverage with good depth and supporting evidence
   - 9-10: Exceptional coverage, addresses all facets with rich detail

2. **Insight** (analysis depth, critical thinking, original perspectives, forward-thinking):
   - 0-3: Surface-level description only, no analysis
   - 4-6: Some analysis but mostly descriptive, limited original thinking
   - 7-8: Strong analytical depth with meaningful insights and reasoning
   - 9-10: Exceptional analysis with novel perspectives and deep understanding

3. **Instruction Following** (task adherence, scope compliance, requirement completeness):
   - 0-3: Fails to address the core research question
   - 4-6: Partially addresses the question but misses key requirements
   - 7-8: Addresses all major requirements with minor omissions
   - 9-10: Fully addresses every aspect of the research task

4. **Readability** (structure, language fluency, technical terminology, presentation):
   - 0-3: Poorly organized, difficult to follow
   - 4-6: Reasonable structure but could be clearer
   - 7-8: Well-structured with clear writing and good flow
   - 9-10: Exceptionally clear, professional structure and presentation"""


def _format_criteria_rubric(criterions: Dict[str, List[Dict[str, Any]]]) -> str:
    """Format task-specific criteria into a rubric string for the judge prompt."""
    parts: List[str] = []
    for dimension in DIMENSIONS:
        criteria_list = criterions.get(dimension, [])
        if not criteria_list:
            continue
        parts.append(f"\n### {dimension.replace('_', ' ').title()}")
        for i, crit in enumerate(criteria_list, 1):
            criterion = crit.get("criterion", "")
            explanation = crit.get("explanation", "")
            weight = crit.get("weight", 0.0)
            parts.append(
                f"  {i}. [{weight:.0%}] {criterion}"
                + (f"\n     {explanation}" if explanation else "")
            )
    return "\n".join(parts)


def _build_judge_prompt(
    *,
    task_prompt: str,
    article: str,
    rubric: str,
) -> str:
    """Build the LLM judge prompt for evaluating a research report."""
    return f"""You are an expert evaluator assessing the quality of an AI-generated research report.

## Original Research Task
{task_prompt}

## Research Report to Evaluate
{article}

## Evaluation Rubric
{rubric}

## Instructions
Evaluate the research report against the rubric criteria across four dimensions:
comprehensiveness, insight, instruction_following, and readability.

Score each dimension on a 0-10 scale.

Return your evaluation as JSON with this exact structure:
```json
{{
  "scores": {{
    "comprehensiveness": <score 0-10>,
    "insight": <score 0-10>,
    "instruction_following": <score 0-10>,
    "readability": <score 0-10>
  }},
  "weighted_total": <weighted score 0-10>,
  "notes": "brief justification for each dimension score"
}}
```

Be a rigorous evaluator. Reserve scores of 9-10 for genuinely excellent work.
A score of 5 represents adequate but unremarkable quality."""


def _parse_judge_response(raw: str) -> Dict[str, Any]:
    """Parse LLM judge response, extracting dimension scores.

    Tries: JSON code block -> balanced braces -> regex fallback.
    """
    if not raw or not raw.strip():
        return {
            "scores": {},
            "weighted_total": 0.0,
            "notes": "Empty judge response",
        }

    # Try JSON code block
    code_block = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if code_block:
        try:
            parsed = json.loads(code_block.group(1))
            if isinstance(parsed, dict):
                return _normalize_response(parsed)
        except json.JSONDecodeError:
            pass

    # Try balanced braces extraction
    candidates: List[str] = []
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

    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and "scores" in parsed:
                return _normalize_response(parsed)
        except json.JSONDecodeError:
            continue

    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return _normalize_response(parsed)
        except json.JSONDecodeError:
            continue

    # Regex fallback: look for individual dimension scores
    scores: Dict[str, float] = {}
    for dim in DIMENSIONS:
        match = re.search(
            rf"{dim}[:\s]*([\d.]+)",
            raw,
            re.IGNORECASE,
        )
        if match:
            try:
                val = float(match.group(1))
                if 0.0 <= val <= 10.0:
                    scores[dim] = val
            except ValueError:
                pass

    if scores:
        LOGGER.warning("Fell back to regex score extraction")
        mean_score = sum(scores.values()) / len(scores) if scores else 0.0
        return {
            "scores": scores,
            "weighted_total": mean_score,
            "notes": "Scores extracted from prose via regex",
        }

    LOGGER.warning("Failed to parse judge response")
    return {
        "scores": {},
        "weighted_total": 0.0,
        "notes": "Failed to parse judge response",
    }


def _normalize_response(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize judge response to standard structure."""
    result: Dict[str, Any] = {"scores": {}, "weighted_total": 0.0, "notes": ""}

    # Extract scores
    scores_data = parsed.get("scores", {})
    if isinstance(scores_data, dict):
        for dim in DIMENSIONS:
            val = scores_data.get(dim)
            if isinstance(val, (int, float)):
                result["scores"][dim] = float(val)

    # Extract weighted_total
    for key in ("weighted_total", "total", "overall_score", "score"):
        if key in parsed and isinstance(parsed[key], (int, float)):
            result["weighted_total"] = float(parsed[key])
            break
    else:
        # Compute mean if no explicit total
        if result["scores"]:
            values = list(result["scores"].values())
            result["weighted_total"] = sum(values) / len(values)

    # Extract notes
    for key in ("notes", "justification", "reasoning"):
        if key in parsed:
            result["notes"] = str(parsed[key])
            break

    return result


class LiveResearchBenchScorer(LLMJudgeScorer):
    """LLM-as-judge scorer for DeepResearchBench deep research tasks.

    Evaluates research reports across four dimensions:
    comprehensiveness, insight, instruction_following, readability.
    Uses task-specific criteria when available from the benchmark data.
    """

    scorer_id = "liveresearch"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response", "score": 0.0}

        # Build rubric — use task-specific criteria if available
        criterions = record.metadata.get("criterions")
        if criterions and isinstance(criterions, dict):
            rubric = _format_criteria_rubric(criterions)
        else:
            rubric = _GENERIC_RUBRIC

        # Get the original research task (strip our wrapper prompt)
        task_prompt = record.problem

        # Build judge prompt
        prompt = _build_judge_prompt(
            task_prompt=task_prompt,
            article=model_answer,
            rubric=rubric,
        )

        try:
            raw = self._ask_judge(prompt, temperature=0.0, max_tokens=4096)
        except Exception as exc:
            LOGGER.error("LLM judge call failed for %s: %s", record.record_id, exc)
            return None, {"error": str(exc), "score": 0.0}

        parsed = _parse_judge_response(raw)
        scores = parsed.get("scores", {})

        # Compute weighted total using task-specific or default weights
        dimension_weights = record.metadata.get("dimension_weight", DEFAULT_WEIGHTS)
        weighted_total = 0.0
        total_weight = 0.0
        for dim in DIMENSIONS:
            dim_score = scores.get(dim, 0.0)
            dim_weight = dimension_weights.get(dim, DEFAULT_WEIGHTS.get(dim, 0.25))
            weighted_total += dim_score * dim_weight
            total_weight += dim_weight

        if total_weight > 0:
            weighted_total /= total_weight
        # Normalize to 0-1 range (scores are 0-10)
        normalized_score = weighted_total / 10.0

        # Threshold: score >= 0.5 (i.e., 5/10 weighted average) is considered passing
        is_correct = normalized_score >= 0.5

        metadata: Dict[str, Any] = {
            "score": normalized_score,
            "dimension_scores": scores,
            "dimension_weights": dimension_weights,
            "weighted_total_0_10": weighted_total,
            "notes": parsed.get("notes", ""),
            "raw_judge_output": raw,
        }

        return is_correct, metadata


__all__ = ["LiveResearchBenchScorer"]
