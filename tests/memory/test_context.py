"""Tests for context injection."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult
from openjarvis.tools.storage.context import (
    _UNTRUSTED_ANNOTATION,
    ContextConfig,
    apply_trust_policy,
    build_context_message,
    format_context,
    inject_context,
)

# -- Fake backend for testing ------------------------------------------------


class _FakeMemory(MemoryBackend):
    """In-memory backend that returns pre-set results."""

    backend_id = "fake"

    def __init__(
        self,
        results: Optional[List[RetrievalResult]] = None,
    ) -> None:
        self._results = results or []

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return uuid.uuid4().hex

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        return self._results[:top_k]

    def delete(self, doc_id: str) -> bool:
        return False

    def clear(self) -> None:
        self._results.clear()


# -- Tests -------------------------------------------------------------------


def test_format_context_with_sources():
    results = [
        RetrievalResult(
            content="Python is great",
            score=1.0,
            source="wiki.md",
        ),
        RetrievalResult(
            content="Java is verbose",
            score=0.8,
            source="notes.txt",
        ),
    ]
    text = format_context(results)
    assert "[Source: wiki.md]" in text
    assert "Python is great" in text
    assert "[Source: notes.txt]" in text


def test_format_context_empty():
    assert format_context([]) == ""


def test_build_context_message_role():
    results = [
        RetrievalResult(content="test", score=1.0, source="s.md"),
    ]
    msg = build_context_message(results)
    assert msg.role == Role.SYSTEM
    assert "knowledge base" in msg.content
    assert "test" in msg.content


def test_inject_context_adds_system_message():
    results = [
        RetrievalResult(
            content="relevant info",
            score=0.9,
            source="doc.md",
        ),
    ]
    backend = _FakeMemory(results)
    messages = [Message(role=Role.USER, content="hello")]
    augmented = inject_context("query", messages, backend)
    assert len(augmented) == 2
    assert augmented[0].role == Role.SYSTEM
    assert "relevant info" in augmented[0].content


def test_inject_context_filters_low_score():
    results = [
        RetrievalResult(content="low score", score=0.01),
    ]
    backend = _FakeMemory(results)
    messages = [Message(role=Role.USER, content="hello")]
    cfg = ContextConfig(min_score=0.1)
    augmented = inject_context(
        "query",
        messages,
        backend,
        config=cfg,
    )
    # Low score filtered out — no context added
    assert len(augmented) == 1


def test_inject_context_respects_max_tokens():
    # Each result has ~100 tokens, max is 150 → only 1 should be included
    content = " ".join(f"word{i}" for i in range(100))
    results = [
        RetrievalResult(content=content, score=1.0, source="a.md"),
        RetrievalResult(content=content, score=0.9, source="b.md"),
    ]
    backend = _FakeMemory(results)
    messages = [Message(role=Role.USER, content="test")]
    cfg = ContextConfig(max_context_tokens=150)
    augmented = inject_context(
        "query",
        messages,
        backend,
        config=cfg,
    )
    assert len(augmented) == 2  # system + user
    # Only one source should be cited
    assert augmented[0].content.count("[Source:") == 1


def test_inject_context_disabled():
    results = [
        RetrievalResult(content="data", score=1.0),
    ]
    backend = _FakeMemory(results)
    messages = [Message(role=Role.USER, content="hello")]
    cfg = ContextConfig(enabled=False)
    augmented = inject_context(
        "query",
        messages,
        backend,
        config=cfg,
    )
    assert len(augmented) == 1


def test_inject_context_no_results_returns_original():
    backend = _FakeMemory([])
    messages = [Message(role=Role.USER, content="hello")]
    augmented = inject_context("query", messages, backend)
    assert augmented is messages


def test_inject_context_publishes_event():
    bus = EventBus(record_history=True)
    results = [
        RetrievalResult(content="info", score=0.9, source="s.md"),
    ]
    backend = _FakeMemory(results)
    messages = [Message(role=Role.USER, content="hello")]

    import openjarvis.tools.storage.context as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        inject_context("query", messages, backend)
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_RETRIEVE]
        assert len(events) == 1
        assert events[0].data["context_injection"] is True
    finally:
        mod.get_event_bus = original


def test_inject_context_does_not_mutate_original():
    results = [
        RetrievalResult(content="info", score=0.9, source="s.md"),
    ]
    backend = _FakeMemory(results)
    messages = [Message(role=Role.USER, content="hello")]
    original_len = len(messages)
    augmented = inject_context("query", messages, backend)
    assert len(messages) == original_len
    assert len(augmented) == original_len + 1


# -- Trust policy ------------------------------------------------------------


def _trusted(content="trusted fact"):
    return RetrievalResult(content=content, score=1.0, source="doc.md")


def _untrusted(content="untrusted fact"):
    return RetrievalResult(
        content=content,
        score=1.0,
        source="auto",
        metadata={"trust": "untrusted"},
    )


def test_apply_trust_policy_drop_removes_untrusted():
    results = [_trusted("keep me"), _untrusted("drop me")]
    filtered = apply_trust_policy(results, "drop")
    assert [r.content for r in filtered] == ["keep me"]


def test_apply_trust_policy_drop_is_default():
    results = [_trusted(), _untrusted()]
    # Default policy (no arg) must be the safe "drop".
    assert apply_trust_policy(results) == apply_trust_policy(results, "drop")
    assert len(apply_trust_policy(results)) == 1


def test_apply_trust_policy_annotate_prefixes_untrusted_only():
    results = [_trusted("clean"), _untrusted("suspicious")]
    annotated = apply_trust_policy(results, "annotate")
    assert len(annotated) == 2
    # Trusted result untouched.
    assert annotated[0].content == "clean"
    # Untrusted result carries the warning prefix but keeps its payload.
    assert annotated[1].content == f"{_UNTRUSTED_ANNOTATION} suspicious"


def test_apply_trust_policy_annotate_does_not_mutate_original():
    original = _untrusted("payload")
    results = [original]
    annotated = apply_trust_policy(results, "annotate")
    # A fresh RetrievalResult is returned; the caller's object is unchanged.
    assert original.content == "payload"
    assert annotated[0] is not original
    assert annotated[0].metadata == original.metadata


def test_apply_trust_policy_unknown_passes_through_unchanged():
    results = [_trusted(), _untrusted()]
    passed = apply_trust_policy(results, "passthrough")
    assert passed == results
    # A new list is returned, not the caller's own.
    assert passed is not results


def test_apply_trust_policy_trust_tag_is_case_insensitive():
    result = RetrievalResult(
        content="x",
        score=1.0,
        metadata={"trust": "  UnTrusted  "},
    )
    assert apply_trust_policy([result], "drop") == []


def test_inject_context_drops_untrusted_result():
    # Only an untrusted result is available → nothing should reach the model.
    backend = _FakeMemory([_untrusted("secret target output")])
    messages = [Message(role=Role.USER, content="hello")]
    augmented = inject_context("query", messages, backend)
    # Fully dropped → original messages returned unchanged.
    assert augmented is messages


def test_inject_context_keeps_trusted_drops_untrusted():
    backend = _FakeMemory([_trusted("verified fact"), _untrusted("injected")])
    messages = [Message(role=Role.USER, content="hello")]
    augmented = inject_context("query", messages, backend)
    assert len(augmented) == 2
    ctx = augmented[0].content
    assert "verified fact" in ctx
    assert "injected" not in ctx


def test_inject_context_annotate_surfaces_untrusted_with_warning():
    backend = _FakeMemory([_untrusted("captured from a scraped page")])
    messages = [Message(role=Role.USER, content="hello")]
    cfg = ContextConfig(untrusted_policy="annotate")
    augmented = inject_context("query", messages, backend, config=cfg)
    assert len(augmented) == 2
    ctx = augmented[0].content
    # The content surfaces, but only behind the unverified-origin caveat.
    assert _UNTRUSTED_ANNOTATION in ctx
    assert "captured from a scraped page" in ctx
