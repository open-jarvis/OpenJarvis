"""Shared retrieval / web-grounding helpers for interactive chat."""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from openjarvis.agents.grounding import (
    query_needs_web_search,
    run_web_search_preflight,
    tool_names_include_web,
)

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig
    from openjarvis.core.types import Message

# Prepended to tier system prompts when the agent uses tools.
WEB_GROUNDING_SYSTEM = (
    "Grounding priority: local models are weak on post-training facts. "
    "When web_search is in your tool list, you MUST call it before answering "
    "questions about current events, news, prices, versions, APIs, laws, "
    "weather, or anything that may have changed recently — do not guess from "
    "weights alone. Cite titles/snippets from tool output. "
    "When memory_retrieve is available, search indexed project knowledge first "
    "for repo-specific facts, then use web_search for external or fresh data. "
    "Use qdrant-find only for collections the user already indexed; do not "
    "chunk or store chat text into Qdrant during the session."
)

LONG_MEMORY_SYSTEM = (
    "Long-session memory: use memory_retrieve (and automatic context blocks) "
    "for prior indexed notes. Index new documents with ``jarvis memory index`` "
    "outside chat — not ad-hoc chunking in the REPL."
)


def ensure_chat_tool_names(
    names: List[str],
    *,
    require_web_search: bool = True,
    require_memory_retrieve: bool = False,
) -> List[str]:
    """Return *names* with required tools appended if missing."""
    out = list(names)
    seen = {n.strip() for n in out if n.strip()}
    if require_web_search and "web_search" not in seen:
        out.append("web_search")
        seen.add("web_search")
    if require_memory_retrieve and "memory_retrieve" not in seen:
        out.append("memory_retrieve")
        seen.add("memory_retrieve")
    return out


def memory_context_messages(
    query: str,
    config: JarvisConfig,
) -> List[Message]:
    """Retrieve indexed memory context for *query* (empty if disabled/unavailable)."""
    if not getattr(config.agent, "context_from_memory", True):
        return []
    from openjarvis.cli.ask import _get_memory_backend
    from openjarvis.tools.storage.context import ContextConfig, inject_context

    backend = _get_memory_backend(config)
    if backend is None:
        return []
    ctx_cfg = ContextConfig(
        top_k=config.memory.context_top_k,
        min_score=config.memory.context_min_score,
        max_context_tokens=config.memory.context_max_tokens,
    )
    injected = inject_context(query, [], backend, config=ctx_cfg)
    return injected if injected else []


def preflight_web_block(user_input: str, *, max_results: int = 8) -> str | None:
    """Run web_search for news/current-events queries; return snippet block."""
    if not query_needs_web_search(user_input):
        return None
    return run_web_search_preflight(user_input, max_results=max_results)


__all__ = [
    "LONG_MEMORY_SYSTEM",
    "WEB_GROUNDING_SYSTEM",
    "ensure_chat_tool_names",
    "memory_context_messages",
    "preflight_web_block",
    "query_needs_web_search",
    "tool_names_include_web",
]
