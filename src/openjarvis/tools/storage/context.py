"""Context injection — retrieve relevant memory and inject into prompts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, List, Optional, Sequence

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.types import Message, Role
from openjarvis.memory.store import RECALLABLE_TRUST_TIERS
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


def _trusted_facts(facts: Sequence[Fact]) -> List[Fact]:
    """Return only facts explicitly safe for model-facing recall."""
    return [fact for fact in facts if bool(getattr(fact, "trusted_for_recall", True))]


def _result_trusted_for_recall(result: RetrievalResult) -> bool:
    """Whether a retrieved document may be placed in model-facing context.

    Documents carry provenance in ``metadata["trust"]`` using the same tier
    vocabulary as facts. A document with no trust key predates provenance
    tagging and stays recallable, so enabling this never silently empties an
    existing knowledge base. Anything else — ``untrusted``, an unknown future
    tier, or metadata that is not a mapping at all — fails closed rather than
    becoming prompt input.
    """
    metadata = getattr(result, "metadata", None)
    if metadata is None:
        return True
    if not isinstance(metadata, Mapping):
        return False
    tier = str(metadata.get("trust", "") or "").strip().lower()
    return tier in RECALLABLE_TRUST_TIERS


def _trusted_results(
    results: Sequence[RetrievalResult],
) -> List[RetrievalResult]:
    """Return only retrieved documents safe for model-facing recall."""
    return [result for result in results if _result_trusted_for_recall(result)]


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
    # Defensive filtering here protects direct callers as well as the normal
    # inject_context() path. Quarantined facts must never become instructions
    # merely because a caller skipped the budget-selection helper.
    facts = _trusted_facts(facts)
    results = _trusted_results(results)
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
    return Message(
        role=Role.SYSTEM,
        content=content,
        metadata={"memory_context": True},
    )


def _merge_context_message(
    messages: List[Message],
    context_message: Message,
) -> List[Message]:
    """Return a copy with context folded into the existing system prompt."""
    system_messages = [message for message in messages if message.role == Role.SYSTEM]
    if not system_messages:
        return [context_message, *messages]

    content = "\n\n".join(
        part
        for part in (
            *(message.text for message in system_messages),
            context_message.text,
        )
        if part
    )
    combined = replace(system_messages[0], content=content)
    # Always place the merged system message FIRST. Ollama (and many chat
    # templates) reject a non-initial system message with
    # "system message must be at the beginning", so preserving the original
    # system position is not safe — a system message may arrive mid-list
    # (e.g. after caller-provided history).
    return [combined] + [m for m in messages if m.role != Role.SYSTEM]


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
        Durable facts captured by the automatic memory service. Quarantined
        provenance tiers are excluded before budgeting or prompt construction,
        as are retrieved documents carrying the same quarantined tiers.
    """
    cfg = config or ContextConfig()
    if not cfg.enabled:
        return messages

    results = backend.retrieve(query, top_k=cfg.top_k) if backend is not None else []

    # Drop quarantined-provenance documents before anything else, so a
    # hostile document cannot consume context budget it will never be
    # allowed to spend.
    results = _trusted_results(results)

    # Filter by minimum score
    results = [r for r in results if r.score >= cfg.min_score]

    # When both sources have data, cap facts at half the total budget so they
    # cannot starve query-specific document retrieval. Unused fact budget is
    # still available to documents. Newest facts win within the fact budget.
    fact_budget = cfg.max_context_tokens
    if results:
        fact_budget //= 2
    selected_facts: List[Fact] = []
    total_tokens = 0
    for fact in reversed(_trusted_facts(facts)):
        tokens = _count_tokens(fact.text)
        if total_tokens + tokens > fact_budget:
            continue
        selected_facts.append(fact)
        total_tokens += tokens

    # Fill the remaining context budget with retrieved documents.
    truncated: List[RetrievalResult] = []
    for r in results:
        tokens = _count_tokens(r.content)
        if total_tokens + tokens > cfg.max_context_tokens:
            # A large top result should not disappear solely because facts
            # consumed their reserved share. Prefer that result when it fits
            # the total budget on its own.
            if not truncated and selected_facts and tokens <= cfg.max_context_tokens:
                selected_facts = []
                total_tokens = 0
            else:
                break
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
    return _merge_context_message(messages, ctx_msg)


__all__ = [
    "ContextConfig",
    "build_context_message",
    "format_context",
    "inject_context",
]
