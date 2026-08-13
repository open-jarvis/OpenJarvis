"""Context injection — retrieve relevant memory and inject into prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Sequence

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.types import Message, Role
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult

if TYPE_CHECKING:
    from openjarvis.memory.store import Fact


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
    facts: Sequence[Fact] = (),
) -> Message:
    """Create a system message with formatted context."""
    sections = []
    if facts:
        fact_text = "\n".join(f"- {fact.text}" for fact in facts)
        sections.append(
            "The following durable facts were remembered from prior "
            "conversations. Use them when relevant to the user's request:\n\n"
            + fact_text
        )
    if results:
        sections.append(
            "The following context was retrieved from the knowledge"
            " base. Use it to inform your response, citing sources"
            " where applicable:\n\n" + format_context(results)
        )
    content = "\n\n".join(sections)
    return Message(role=Role.SYSTEM, content=content)


def inject_context(
    query: str,
    messages: List[Message],
    backend: Optional[MemoryBackend],
    *,
    config: Optional[ContextConfig] = None,
    facts: Sequence[Fact] = (),
) -> List[Message]:
    """Retrieve relevant context and prepend it to *messages*.

    Returns a **new** list — the original list is not mutated.
    Automatic-memory facts are included independently of the retrieval
    backend, so persisted facts remain recallable even when the document
    store is empty. If no facts or results are available, returns the original
    messages unchanged.

    Parameters
    ----------
    query:
        The user query to search for.
    messages:
        The existing message list.
    backend:
        The memory backend to search, or ``None`` when only facts are available.
    config:
        Context injection settings (uses defaults if ``None``).
    facts:
        Durable facts captured by the automatic memory service.
    """
    cfg = config or ContextConfig()
    if not cfg.enabled:
        return messages

    results = backend.retrieve(query, top_k=cfg.top_k) if backend is not None else []

    # Filter by minimum score
    results = [r for r in results if r.score >= cfg.min_score]

    # Spend the context budget on durable facts first. Newest facts win if the
    # store grows beyond the configured prompt budget.
    selected_facts: List[Fact] = []
    total_tokens = 0
    for fact in reversed(facts):
        tokens = _count_tokens(fact.text)
        if total_tokens + tokens > cfg.max_context_tokens:
            continue
        selected_facts.append(fact)
        total_tokens += tokens

    # Fill the remaining context budget with retrieved documents.
    truncated: List[RetrievalResult] = []
    for r in results:
        tokens = _count_tokens(r.content)
        if total_tokens + tokens > cfg.max_context_tokens:
            break
        truncated.append(r)
        total_tokens += tokens

    if not selected_facts and not truncated:
        return messages

    # Publish event
    bus = get_event_bus()
    bus.publish(
        EventType.MEMORY_RETRIEVE,
        {
            "context_injection": True,
            "query": query,
            "num_results": len(truncated),
            "num_facts": len(selected_facts),
            "total_tokens": total_tokens,
        },
    )

    # Build context message and prepend
    ctx_msg = build_context_message(truncated, selected_facts)
    return [ctx_msg] + list(messages)


__all__ = [
    "ContextConfig",
    "build_context_message",
    "format_context",
    "inject_context",
]
