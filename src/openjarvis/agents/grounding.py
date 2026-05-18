"""Heuristics for mandatory web grounding before LLM answers."""

from __future__ import annotations

import re
from typing import Any, List, Sequence

# Queries that need live web results, not training weights.
_WEB_QUERY_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"wiadomo[sś]ci|news|aktualn|dzisiaj|wczoraj|teraz|najnowsz"
    r"|ze\s+[śs]wiata|from\s+the\s+world|current\s+events"
    r"|web[-\s]?search|wyszukaj|znajd[zź]|poszukaj|sprawd[zź]\s+w\s+si"
    r"|w\s+internecie|online|google|pogoda|weather"
    r"|co\s+si[eę]\s+dzi|what\s+happened|latest\s+on"
    r")",
)

# Meta questions about capability — do not force search.
_META_TOOL_RE = re.compile(
    r"(?i)^\s*(czy\s+)?(używasz|masz|can you use|do you have)\s+.*web",
)


def query_needs_web_search(text: str) -> bool:
    """Return True if *text* should trigger web_search before answering."""
    t = (text or "").strip()
    if not t or _META_TOOL_RE.search(t):
        return False
    return bool(_WEB_QUERY_RE.search(t))


def web_search_used(tool_results: Sequence[Any]) -> bool:
    """True if a successful web_search appears in agent tool results."""
    for tr in tool_results:
        name = str(getattr(tr, "tool_name", "") or "")
        if name == "web_search" and bool(getattr(tr, "success", False)):
            return True
    return False


def tool_names_include_web(tools: List[Any]) -> bool:
    for t in tools or []:
        spec = getattr(t, "spec", None)
        if spec is not None and getattr(spec, "name", "") == "web_search":
            return True
    return False


def run_web_search_preflight(query: str, *, max_results: int = 8) -> str | None:
    """Execute web_search and return formatted snippets, or None on failure."""
    from openjarvis.tools.web_search import WebSearchTool

    tool = WebSearchTool()
    result = tool.execute(query=query, max_results=max_results)
    if not result.success:
        return None
    body = (result.content or "").strip()
    return body or None


__all__ = [
    "query_needs_web_search",
    "run_web_search_preflight",
    "tool_names_include_web",
    "web_search_used",
]
