"""Shared query classification utilities for routing policies.

Extracted from ``trace_policy.py`` so multiple modules can use
``classify_query()`` without depending on the full policy.
"""

from __future__ import annotations

import re

_CODE_RE = re.compile(
    r"```|`[^`]+`|\bdef\s|\bclass\s|\bimport\s|\bfunction\s",
    re.IGNORECASE,
)
_MATH_RE = re.compile(
    r"\bsolve\b|\bintegral\b|\bequation\b|\bcalculate\b|\bcompute\b",
    re.IGNORECASE,
)


def classify_query(query: str) -> str:
    """Classify a query into a broad category for routing."""
    if _CODE_RE.search(query):
        return "code"
    if _MATH_RE.search(query):
        return "math"
    if len(query) < 50:
        return "short"
    if len(query) > 500:
        return "long"
    return "general"


__all__ = ["classify_query"]
