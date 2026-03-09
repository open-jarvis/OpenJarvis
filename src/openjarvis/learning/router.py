"""Heuristic model router — selects the best model based on query characteristics."""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import RoutingContext
from openjarvis.learning._stubs import QueryAnalyzer, RouterPolicy

logger = logging.getLogger(__name__)

# Detection patterns
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
_REASONING_KEYWORDS = re.compile(
    r"\bexplain\b|\banalyze\b|\bcompare\b|\bwhy\b"
    r"|\bstep[- ]by[- ]step\b|\breason\b|\bthink\b",
    re.IGNORECASE,
)


def build_routing_context(query: str, *, urgency: float = 0.5) -> RoutingContext:
    """Populate a ``RoutingContext`` from a raw query string."""
    return RoutingContext(
        query=query,
        query_length=len(query),
        has_code=bool(_CODE_PATTERNS.search(query)),
        has_math=bool(_MATH_PATTERNS.search(query)),
        urgency=urgency,
    )


def _model_size(key: str) -> float:
    """Return parameter count for a registered model, or 0 if not found."""
    try:
        spec = ModelRegistry.get(key)
        return spec.parameter_count_b
    except (KeyError, AttributeError) as exc:
        logger.debug("Failed to compute model score: %s", exc)
        return 0.0


def _find_model_by_tag(available: List[str], tag: str) -> Optional[str]:
    """Find the first available model whose key contains *tag* (case-insensitive)."""
    tag_lower = tag.lower()
    for key in available:
        if tag_lower in key.lower():
            return key
    return None


def _largest_model(available: List[str]) -> Optional[str]:
    """Return the model with the largest parameter count from the available list."""
    if not available:
        return None
    best = available[0]
    best_size = _model_size(best)
    for key in available[1:]:
        size = _model_size(key)
        if size > best_size:
            best = key
            best_size = size
    return best


def _smallest_model(available: List[str]) -> Optional[str]:
    """Return the smallest-parameter model from *available*."""
    if not available:
        return None
    best = available[0]
    best_size = _model_size(best) or float("inf")
    for key in available[1:]:
        size = _model_size(key)
        if 0 < size < best_size:
            best = key
            best_size = size
    return best


class HeuristicRouter(RouterPolicy):
    """Rule-based model router.

    Rules (applied in order):
    1. Code detected → prefer model with "code"/"coder" in name
    2. Math detected → prefer larger model
    3. Short query (<50 chars, no code/math) → prefer smaller/faster model
    4. Long/complex query (>500 chars OR reasoning keywords) → prefer larger model
    5. High urgency (>0.8) → override to smaller model
    6. Default fallback → default_model → fallback_model → first available
    """

    def __init__(
        self,
        available_models: List[str] | None = None,
        *,
        default_model: str = "",
        fallback_model: str = "",
    ) -> None:
        self._available = available_models or []
        self._default = default_model
        self._fallback = fallback_model

    @property
    def available_models(self) -> List[str]:
        return list(self._available)

    def select_model(self, context: RoutingContext) -> str:
        available = self._available or list(ModelRegistry.keys())
        if not available:
            return self._default or self._fallback or ""

        # Rule 5: High urgency overrides everything → smallest model
        if context.urgency > 0.8:
            return _smallest_model(available) or available[0]

        # Rule 1: Code detected → prefer model with code/coder in name
        if context.has_code:
            code_model = (
                _find_model_by_tag(available, "code")
                or _find_model_by_tag(available, "coder")
            )
            if code_model:
                return code_model
            # Fall through to larger model for code
            return _largest_model(available) or available[0]

        # Rule 2: Math detected → prefer larger model
        if context.has_math:
            return _largest_model(available) or available[0]

        # Rule 3: Short simple query → prefer smaller model
        if context.query_length < 50:
            return _smallest_model(available) or available[0]

        # Rule 4: Long/complex query → prefer larger model
        if context.query_length > 500 or _REASONING_KEYWORDS.search(context.query):
            return _largest_model(available) or available[0]

        # Rule 6: Default fallback
        if self._default and self._default in available:
            return self._default
        if self._fallback and self._fallback in available:
            return self._fallback
        return available[0]


class DefaultQueryAnalyzer(QueryAnalyzer):
    """Default query analyzer wrapping the heuristic build_routing_context function."""

    def analyze(self, query: str, **kwargs: object) -> RoutingContext:
        urgency = kwargs.get("urgency", 0.5)
        if not isinstance(urgency, (int, float)):
            urgency = 0.5
        return build_routing_context(query, urgency=urgency)


__all__ = ["DefaultQueryAnalyzer", "HeuristicRouter", "build_routing_context"]
