"""Pass-1 task classifier for lane-aware routing.

This is intentionally heuristic and lightweight. It maps a raw query to the
repo's task ontology classes so the router can choose a capability lane before
it chooses a specific model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskClassification:
    task_class: str
    confidence: float


_VISION_PATTERNS = re.compile(
    r"\b(image|screenshot|diagram|pdf|photo|picture|scan|ocr|visual|vision)\b",
    re.IGNORECASE,
)
_CODE_COMPLEX_PATTERNS = re.compile(
    r"\b(architecture|multi-file|root cause|intermittent|concurrency|debug|"
    r"refactor|design|system design|novel algorithm)\b",
    re.IGNORECASE,
)
_CODE_PATTERNS = re.compile(
    r"\b(code|python|javascript|typescript|rust|go|java|sql|bash|shell|script|"
    r"function|class|module|test|patch|bug|repo|compile|failing test)\b",
    re.IGNORECASE,
)
_RESEARCH_PATTERNS = re.compile(
    r"\b(research|source|sources|read this|read these|synthesize|synthesis|"
    r"compare sources|citation|trend|competitor|analyze documents?)\b",
    re.IGNORECASE,
)
_SUMMARIZE_PATTERNS = re.compile(
    r"\b(summarize|summary|tl;dr|condense|key points|brief overview)\b",
    re.IGNORECASE,
)
_CLASSIFY_PATTERNS = re.compile(
    r"\b(classify|categorize|tag|label|triage|route|which bucket|yes or no|"
    r"binary decision)\b",
    re.IGNORECASE,
)
_EXTRACT_PATTERNS = re.compile(
    r"\b(extract|pull out|parse|structured data|fields?|entities?)\b",
    re.IGNORECASE,
)
_REWRITE_PATTERNS = re.compile(
    r"\b(rewrite|rephrase|improve wording|adjust tone|edit this text|draft)\b",
    re.IGNORECASE,
)
_COMPARE_PATTERNS = re.compile(
    r"\b(compare|rank|pros and cons|trade-offs?)\b",
    re.IGNORECASE,
)
_LONG_CONTEXT_PATTERNS = re.compile(
    r"\b(long document|large document|many documents|across sources|full corpus|"
    r"context window|transcript|entire report)\b",
    re.IGNORECASE,
)


def classify_task(query: str) -> TaskClassification:
    q = query.strip()
    if not q:
        return TaskClassification("classify", 0.2)

    if _VISION_PATTERNS.search(q):
        return TaskClassification("source-reading", 0.9)
    if _LONG_CONTEXT_PATTERNS.search(q):
        return TaskClassification("synthesis", 0.85)
    if _CODE_COMPLEX_PATTERNS.search(q):
        if (
            "debug" in q.lower()
            or "root cause" in q.lower()
            or "intermittent" in q.lower()
        ):
            return TaskClassification("debug-complex", 0.9)
        if "refactor" in q.lower():
            return TaskClassification("refactor", 0.9)
        if "architecture" in q.lower() or "design" in q.lower():
            return TaskClassification("architecture-review", 0.85)
        return TaskClassification("code-complex", 0.8)
    if _CODE_PATTERNS.search(q):
        if "test" in q.lower():
            return TaskClassification("test-generation", 0.85)
        if "bug" in q.lower() or "fix" in q.lower():
            return TaskClassification("debug-simple", 0.8)
        return TaskClassification("code-simple", 0.75)
    if _RESEARCH_PATTERNS.search(q):
        if "sources" in q.lower() or "synthesis" in q.lower():
            return TaskClassification("synthesis", 0.85)
        if "read" in q.lower():
            return TaskClassification("source-reading", 0.8)
        return TaskClassification("source-finding", 0.75)
    if _SUMMARIZE_PATTERNS.search(q):
        return TaskClassification("summarize", 0.9)
    if _EXTRACT_PATTERNS.search(q):
        return TaskClassification("extract", 0.85)
    if _REWRITE_PATTERNS.search(q):
        return TaskClassification("rewrite", 0.8)
    if _COMPARE_PATTERNS.search(q):
        return TaskClassification("compare", 0.8)
    if _CLASSIFY_PATTERNS.search(q):
        return TaskClassification("classify", 0.85)
    return TaskClassification("summarize", 0.45)


__all__ = ["TaskClassification", "classify_task"]
