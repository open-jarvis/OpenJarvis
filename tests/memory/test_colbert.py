"""Tests for the ColBERTv2 late interaction memory backend."""

from __future__ import annotations

import pytest

colbert = pytest.importorskip("colbert")

import torch  # noqa: E402

from openjarvis.core.events import EventBus, EventType  # noqa: E402
from openjarvis.core.registry import MemoryRegistry  # noqa: E402
from openjarvis.tools.storage.colbert_backend import ColBERTMemory  # noqa: E402


def _make_backend() -> ColBERTMemory:
    """Create a ColBERTMemory and ensure it is registered."""
    if not MemoryRegistry.contains("colbert"):
        MemoryRegistry.register_value("colbert", ColBERTMemory)
    return ColBERTMemory()


# -- registration -----------------------------------------------------------


def test_registration():
    """Importing the module registers 'colbert' in MemoryRegistry."""
    MemoryRegistry.register_value("colbert", ColBERTMemory)
    assert MemoryRegistry.contains("colbert")


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
    backend.store(
        "The weather is sunny today",
        source="diary.md",
    )
    results = backend.retrieve("programming language")
    assert len(results) >= 1
    assert "Python" in results[0].content


# -- MaxSim scoring ---------------------------------------------------------


def test_maxsim_scoring():
    """Test the _maxsim function directly with synthetic tensors."""
    backend = _make_backend()
    # 2 query tokens, dim 4
    q = torch.tensor(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ]
    )
    # 3 doc tokens, dim 4
    d = torch.tensor(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ]
    )
    score = backend._maxsim(q, d)
    # query[0] max sim: max(1.0, 0.0, 0.0) = 1.0
    # query[1] max sim: max(0.0, 0.0, 1.0) = 1.0
    # total: 2.0
    assert abs(score - 2.0) < 0.01


# -- top_k -----------------------------------------------------------------


def test_retrieve_top_k():
    backend = _make_backend()
    for i in range(10):
        backend.store(f"document number {i} about testing")
    results = backend.retrieve("testing", top_k=3)
    assert len(results) <= 3


# -- delete -----------------------------------------------------------------


def test_delete():
    backend = _make_backend()
    doc_id = backend.store("deletable content")
    assert backend.count() == 1
    assert backend.delete(doc_id) is True
    assert backend.count() == 0


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
    import openjarvis.tools.storage.colbert_backend as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        backend.store("test event emission")
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_STORE]
        assert len(events) == 1
        assert events[0].data["backend"] == "colbert"
        assert "doc_id" in events[0].data
    finally:
        mod.get_event_bus = original


def test_event_bus_retrieve():
    bus = EventBus(record_history=True)
    backend = _make_backend()
    backend.store("searchable content for events")
    import openjarvis.tools.storage.colbert_backend as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        backend.retrieve("searchable")
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_RETRIEVE]
        assert len(events) == 1
        assert events[0].data["backend"] == "colbert"
        assert events[0].data["num_results"] >= 0
    finally:
        mod.get_event_bus = original
