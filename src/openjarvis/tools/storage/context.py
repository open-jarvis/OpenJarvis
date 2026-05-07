"""Context injection — retrieve relevant memory and inject into prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.types import Message, Role
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult


@dataclass(slots=True)
class ContextConfig:
    """Controls how retrieved context is injected into prompts."""

    enabled: bool = True
    top_k: int = 5
    min_score: float = 0.0
    max_context_tokens: int = 2048


def _count_tokens(text: str) -> int:
    """Approximate token count via whitespace split."""
    return len(text.split())


def format_context(results: List[RetrievalResult]) -> str:
    """Format retrieval results into a context block.

    Each result is prefixed with its source attribution.
    """
    if not results:
        return ""

    lines = []
    for r in results:
        source_tag = f"[Source: {r.source}]" if r.source else ""
        if source_tag:
            lines.append(f"{source_tag} {r.content}")
        else:
            lines.append(r.content)

    return "\n\n".join(lines)


def build_context_message(
    results: List[RetrievalResult],
) -> Message:
    """Create a system message with formatted context."""
    context_text = format_context(results)
    content = (
        "The following context was retrieved from the knowledge"
        " base. Use it to inform your response, citing sources"
        " where applicable:\n\n" + context_text
    )
    return Message(role=Role.SYSTEM, content=content)


def inject_context(
    query: str,
    messages: List[Message],
    backend: MemoryBackend,
    *,
    config: Optional[ContextConfig] = None,
) -> List[Message]:
    """Retrieve relevant context and prepend it to *messages*.

    Returns a **new** list — the original list is not mutated.
    If no results pass the score threshold, returns the original
    messages unchanged.

    Parameters
    ----------
    query:
        The user query to search for.
    messages:
        The existing message list.
    backend:
        The memory backend to search.
    config:
        Context injection settings (uses defaults if ``None``).
    """
    cfg = config or ContextConfig()
    if not cfg.enabled:
        return messages

    results = backend.retrieve(query, top_k=cfg.top_k)

    # Filter by minimum score
    results = [r for r in results if r.score >= cfg.min_score]

    if not results:
        return messages

    # Truncate to max_context_tokens
    truncated: List[RetrievalResult] = []
    total_tokens = 0
    for r in results:
        tokens = _count_tokens(r.content)
        if total_tokens + tokens > cfg.max_context_tokens:
            break
        truncated.append(r)
        total_tokens += tokens

    if not truncated:
        return messages

    # Publish event
    bus = get_event_bus()
    bus.publish(
        EventType.MEMORY_RETRIEVE,
        {
            "context_injection": True,
            "query": query,
            "num_results": len(truncated),
            "total_tokens": total_tokens,
        },
    )

    # Build context message and prepend
    ctx_msg = build_context_message(truncated)
    return [ctx_msg] + list(messages)


__all__ = [
    "ContextConfig",
    "build_context_message",
    "format_context",
    "inject_context",
]
