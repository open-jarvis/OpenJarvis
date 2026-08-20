"""Query complexity analyzer — scores queries and suggests token budgets.

Produces a numeric complexity score (0.0–1.0) and a suggested
``max_tokens`` budget based on query characteristics such as length,
domain signals (code, math, multi-step reasoning), and whether the
target model is a thinking model that needs extra headroom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from openjarvis.core.types import RoutingContext
from openjarvis.learning._stubs import QueryAnalyzer

# ---------------------------------------------------------------------------
# Signal patterns
# ---------------------------------------------------------------------------

_CODE_PATTERNS = re.compile(
    r"```|`[^`]+`|\bdef\s|\bclass\s|\bimport\s|\bfunction\s|\bconst\s|\bvar\s|\blet\s|"
    r"\bif\s*\(|->|=>|\{\s*\}|\bfor\s+\w+\s+in\s|#include|System\.out",
    re.IGNORECASE,
)
_MATH_PATTERNS = re.compile(
    r"\bsolve\b|\bintegral\b|\bequation\b|\bproof\b|\bderivative\b|\bmatrix\b|"
    r"\btheorem\b|\bcalculate\b|\bcompute\b|\bsigma\b|\bsum\b|\blimit\b|\bprobability\b",
    re.IGNORECASE,
)
_REASONING_PATTERNS = re.compile(
    r"\bexplain\b|\banalyze\b|\bcompare\b|\bwhy\b"
    r"|\bstep[- ]by[- ]step\b|\breason\b|\bthink\b"
    r"|\bpros\s+and\s+cons\b|\btrade-?\s*offs?\b|\bevaluate\b",
    re.IGNORECASE,
)
_MULTI_STEP_PATTERNS = re.compile(
    r"\bthen\b.*\bthen\b|\bfirst\b.*\bnext\b|\bstep\s*\d"
    r"|\b(?:and\s+also|additionally|furthermore)\b"
    r"|\b\d+\.\s",
    re.IGNORECASE | re.DOTALL,
)
_CREATIVE_PATTERNS = re.compile(
    r"\bwrite\b.*\b(?:essay|story|article|report|poem)\b"
    r"|\bgenerate\b.*\b(?:code|script|program)\b"
    r"|\bcreate\b|\bdesign\b|\bdraft\b|\bcompose\b",
    re.IGNORECASE,
)

# Models known to use internal chain-of-thought that consumes output tokens.
_THINKING_MODEL_PATTERNS = re.compile(
    r"qwen3\.5|qwq|deepseek-r1|o1-|o3-|o4-", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Token budget tiers
# ---------------------------------------------------------------------------

_TOKEN_TIERS = {
    "trivial": 1024,  # greetings, yes/no, factoid lookups
    "simple": 2048,  # short answers, definitions
    "moderate": 4096,  # explanations, summaries
    "complex": 8192,  # analysis, code generation, multi-step
    "very_complex": 16384,  # long-form, multi-part reasoning
}

# Thinking models need extra headroom for internal chain-of-thought.
_THINKING_TOKEN_MULTIPLIER = 2


# ---------------------------------------------------------------------------
# Complexity scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComplexityResult:
    """Output of the complexity analysis."""

    score: float  # 0.0–1.0
    tier: str
    suggested_max_tokens: int
    signals: dict


def _count_questions(query: str) -> int:
    """Count the number of question marks in the query."""
    return query.count("?")


def _count_sub_tasks(query: str) -> int:
    """Estimate the number of sub-tasks or enumerated items."""
    numbered = len(re.findall(r"^\s*\d+[.)]\s", query, re.MULTILINE))
    bulleted = len(re.findall(r"^\s*[-*]\s", query, re.MULTILINE))
    return numbered + bulleted


def score_complexity(query: str) -> ComplexityResult:
    """Score a query's complexity from 0.0 (trivial) to 1.0 (very complex).

    The score is a weighted combination of independent signals, each
    contributing a fraction between 0 and 1.  Weights reflect how much
    each signal correlates with the amount of reasoning and output
    tokens a model will need.
    """
    signals: dict = {}
    score = 0.0

    # --- Length signal (0–0.20) ---
    length = len(query)
    if length < 20:
        length_score = 0.0
    elif length < 100:
        length_score = 0.3
    elif length < 300:
        length_score = 0.6
    elif length < 800:
        length_score = 0.8
    else:
        length_score = 1.0
    signals["length"] = length_score
    score += 0.20 * length_score

    # --- Domain signals (0–0.25) ---
    has_code = bool(_CODE_PATTERNS.search(query))
    has_math = bool(_MATH_PATTERNS.search(query))
    domain_score = 0.0
    if has_code:
        domain_score = max(domain_score, 0.7)
    if has_math:
        domain_score = max(domain_score, 0.8)
    if has_code and has_math:
        domain_score = 1.0
    signals["domain"] = domain_score
    signals["has_code"] = has_code
    signals["has_math"] = has_math
    score += 0.25 * domain_score

    # --- Reasoning signal (0–0.25) ---
    has_reasoning = bool(_REASONING_PATTERNS.search(query))
    has_multi_step = bool(_MULTI_STEP_PATTERNS.search(query))
    reasoning_score = 0.0
    if has_reasoning:
        reasoning_score = 0.6
    if has_multi_step:
        reasoning_score = max(reasoning_score, 0.8)
    if has_reasoning and has_multi_step:
        reasoning_score = 1.0
    signals["reasoning"] = reasoning_score
    signals["has_reasoning"] = has_reasoning
    signals["has_multi_step"] = has_multi_step
    score += 0.25 * reasoning_score

    # --- Question / sub-task count (0–0.15) ---
    n_questions = _count_questions(query)
    n_subtasks = _count_sub_tasks(query)
    multi_part = n_questions + n_subtasks
    if multi_part <= 1:
        multi_score = 0.0
    elif multi_part <= 3:
        multi_score = 0.5
    else:
        multi_score = 1.0
    signals["multi_part"] = multi_score
    signals["n_questions"] = n_questions
    signals["n_subtasks"] = n_subtasks
    score += 0.15 * multi_score

    # --- Creative / generative signal (0–0.15) ---
    has_creative = bool(_CREATIVE_PATTERNS.search(query))
    creative_score = 0.7 if has_creative else 0.0
    signals["creative"] = creative_score
    signals["has_creative"] = has_creative
    score += 0.15 * creative_score

    # Clamp
    score = max(0.0, min(1.0, score))

    # Map to tier
    if score < 0.15:
        tier = "trivial"
    elif score < 0.30:
        tier = "simple"
    elif score < 0.55:
        tier = "moderate"
    elif score < 0.80:
        tier = "complex"
    else:
        tier = "very_complex"

    suggested_max_tokens = _TOKEN_TIERS[tier]

    return ComplexityResult(
        score=round(score, 3),
        tier=tier,
        suggested_max_tokens=suggested_max_tokens,
        signals=signals,
    )


def is_thinking_model(model_name: str) -> bool:
    """Return True if the model is known to use internal chain-of-thought."""
    return bool(_THINKING_MODEL_PATTERNS.search(model_name))


def adjust_tokens_for_model(suggested: int, model_name: Optional[str] = None) -> int:
    """Multiply the token budget when the target is a thinking model."""
    if model_name and is_thinking_model(model_name):
        return suggested * _THINKING_TOKEN_MULTIPLIER
    return suggested


# ---------------------------------------------------------------------------
# QueryAnalyzer implementation
# ---------------------------------------------------------------------------


class ComplexityQueryAnalyzer(QueryAnalyzer):
    """Query analyzer that produces a complexity-aware RoutingContext.

    Drop-in replacement for ``DefaultQueryAnalyzer`` — adds
    ``complexity_score``, ``has_reasoning``, and ``suggested_max_tokens``
    to the returned ``RoutingContext``.
    """

    def analyze(self, query: str, **kwargs: object) -> RoutingContext:
        urgency = kwargs.get("urgency", 0.5)
        if not isinstance(urgency, (int, float)):
            urgency = 0.5
        model_name = kwargs.get("model")
        if not isinstance(model_name, str):
            model_name = None

        result = score_complexity(query)
        tokens = adjust_tokens_for_model(result.suggested_max_tokens, model_name)

        return RoutingContext(
            query=query,
            query_length=len(query),
            has_code=result.signals.get("has_code", False),
            has_math=result.signals.get("has_math", False),
            has_reasoning=result.signals.get("has_reasoning", False),
            urgency=float(urgency),
            complexity_score=result.score,
            suggested_max_tokens=tokens,
            metadata={"complexity_tier": result.tier, "signals": result.signals},
        )


__all__ = [
    "ComplexityQueryAnalyzer",
    "ComplexityResult",
    "adjust_tokens_for_model",
    "is_thinking_model",
    "score_complexity",
]
