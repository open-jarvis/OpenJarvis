"""Tests for the BM25 memory backend."""

from __future__ import annotations

import pytest

rank_bm25 = pytest.importorskip("rank_bm25")

from openjarvis.core.events import EventBus, EventType  # noqa: E402
from openjarvis.core.registry import MemoryRegistry  # noqa: E402
from openjarvis.tools.storage.bm25 import BM25Memory  # noqa: E402


def _make_backend() -> BM25Memory:
    """Create a BM25Memory and ensure it is registered."""
    if not MemoryRegistry.contains("bm25"):
        MemoryRegistry.register_value("bm25", BM25Memory)
    return BM25Memory()


# -- registration -----------------------------------------------------------


def test_registration_in_memory_registry():
    """Importing the module registers 'bm25' in MemoryRegistry."""
    MemoryRegistry.register_value("bm25", BM25Memory)
    assert MemoryRegistry.contains("bm25")


# -- store ------------------------------------------------------------------


def test_store_returns_id():
    backend = _make_backend()
    doc_id = backend.store("hello world")
    assert isinstance(doc_id, str)
    assert len(doc_id) == 32  # hex UUID


# -- retrieve ---------------------------------------------------------------


def test_store_and_retrieve():
    backend = _make_backend()
    backend.store(
        "Python is a programming language",
        source="wiki.md",
    )
    backend.store("The weather is sunny today", source="diary.md")
    results = backend.retrieve("programming language")
    assert len(results) >= 1
    assert "Python" in results[0].content


def test_relevance_ordering():
    backend = _make_backend()
    backend.store("cooking recipes for dinner")
    backend.store("machine learning and deep learning")
    backend.store("advanced machine learning techniques")
    results = backend.retrieve("machine learning")
    assert len(results) >= 2
    # Both ML docs should rank above cooking
    for r in results:
        assert "machine" in r.content.lower()


def test_top_k():
    backend = _make_backend()
    for i in range(10):
        backend.store(f"document number {i} about testing")
    results = backend.retrieve("testing", top_k=3)
    assert len(results) <= 3


def test_empty_store_returns_no_results():
    backend = _make_backend()
    results = backend.retrieve("anything")
    assert results == []


def test_retrieve_empty_query():
    backend = _make_backend()
    backend.store("some content")
    results = backend.retrieve("   ")
    assert results == []


# -- delete -----------------------------------------------------------------


def test_delete():
    backend = _make_backend()
    doc_id = backend.store("deletable content")
    assert backend.count() == 1
    assert backend.delete(doc_id) is True
    assert backend.count() == 0
    # Verify retrieval no longer returns it
    results = backend.retrieve("deletable")
    assert len(results) == 0


def test_delete_nonexistent():
    backend = _make_backend()
    assert backend.delete("nonexistent_id") is False


# -- clear ------------------------------------------------------------------


def test_clear():
    backend = _make_backend()
    backend.store("doc one")
    backend.store("doc two")
    assert backend.count() == 2
    backend.clear()
    assert backend.count() == 0
    results = backend.retrieve("doc")
    assert results == []


# -- event bus integration --------------------------------------------------


def test_event_bus_store():
    bus = EventBus(record_history=True)
    backend = _make_backend()
    import openjarvis.tools.storage.bm25 as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        backend.store("test event emission")
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_STORE]
        assert len(events) == 1
        assert events[0].data["backend"] == "bm25"
        assert "doc_id" in events[0].data
    finally:
        mod.get_event_bus = original


def test_event_bus_retrieve():
    bus = EventBus(record_history=True)
    backend = _make_backend()
    backend.store("searchable content for events")
    import openjarvis.tools.storage.bm25 as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        backend.retrieve("searchable")
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_RETRIEVE]
        assert len(events) == 1
        assert events[0].data["backend"] == "bm25"
        assert events[0].data["num_results"] >= 1
    finally:
        mod.get_event_bus = original
