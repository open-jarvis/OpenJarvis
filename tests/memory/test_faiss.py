"""Tests for the FAISS dense retrieval memory backend."""

from __future__ import annotations

import pytest

faiss = pytest.importorskip("faiss")

import numpy as np  # noqa: E402

from openjarvis.core.events import (  # noqa: E402
    EventBus,
    EventType,
)
from openjarvis.core.registry import MemoryRegistry  # noqa: E402
from openjarvis.tools.storage._stubs import RetrievalResult  # noqa: E402
from openjarvis.tools.storage.embeddings import Embedder  # noqa: E402
from openjarvis.tools.storage.faiss_backend import (  # noqa: E402
    FAISSMemory,
)

# ------------------------------------------------------------------
# Fake embedder (avoids sentence-transformers dependency)
# ------------------------------------------------------------------


class _FakeEmbedder(Embedder):
    """Deterministic hash-based fake embedder for testing."""

    def embed(self, texts: list[str]) -> np.ndarray:  # type: ignore[override]
        results = []
        for text in texts:
            rng = np.random.RandomState(hash(text) % 2**31)
            vec = rng.randn(64).astype(np.float32)
            results.append(vec)
        return np.array(results) if results else np.empty((0, 64), dtype=np.float32)

    def dim(self) -> int:
        return 64


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_backend() -> FAISSMemory:
    """Create a FAISSMemory with the fake embedder.

    Re-registers the class since conftest clears registries.
    """
    if not MemoryRegistry.contains("faiss"):
        MemoryRegistry.register_value("faiss", FAISSMemory)
    return FAISSMemory(embedder=_FakeEmbedder())


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_registration():
    """Importing the module registers 'faiss' in MemoryRegistry."""
    MemoryRegistry.register_value("faiss", FAISSMemory)
    assert MemoryRegistry.contains("faiss")


def test_store_returns_id():
    """store() returns a 32-char hex UUID."""
    backend = _make_backend()
    doc_id = backend.store("hello world")
    assert isinstance(doc_id, str)
    assert len(doc_id) == 32


def test_store_and_retrieve_semantic():
    """Stored documents can be retrieved by query."""
    backend = _make_backend()
    backend.store("Python is a programming language")
    backend.store("The weather is sunny today")
    results = backend.retrieve("programming language")
    assert len(results) >= 1
    assert all(isinstance(r, RetrievalResult) for r in results)


def test_top_k():
    """retrieve() respects the top_k parameter."""
    backend = _make_backend()
    for i in range(10):
        backend.store(f"document number {i} about testing")
    results = backend.retrieve("testing", top_k=3)
    assert len(results) <= 3


def test_retrieve_empty():
    """Querying an empty backend returns an empty list."""
    backend = _make_backend()
    results = backend.retrieve("anything")
    assert results == []


def test_delete_soft():
    """delete() soft-deletes; doc no longer appears in results."""
    backend = _make_backend()
    doc_id = backend.store("deletable content")
    assert backend.delete(doc_id) is True
    # Second delete returns False
    assert backend.delete(doc_id) is False
    results = backend.retrieve("deletable content")
    for r in results:
        assert r.content != "deletable content"


def test_delete_nonexistent():
    """delete() returns False for unknown ids."""
    backend = _make_backend()
    assert backend.delete("nonexistent_id") is False


def test_clear():
    """clear() resets all storage and the FAISS index."""
    backend = _make_backend()
    backend.store("doc one")
    backend.store("doc two")
    backend.clear()
    assert backend._index.ntotal == 0
    assert len(backend._documents) == 0
    assert len(backend._id_map) == 0
    assert len(backend._deleted) == 0
    results = backend.retrieve("doc")
    assert results == []


def test_cosine_similarity_ordering():
    """Results are ordered by descending cosine similarity."""
    backend = _make_backend()
    backend.store("alpha beta gamma")
    backend.store("delta epsilon zeta")
    backend.store("alpha beta gamma delta")
    results = backend.retrieve("alpha beta gamma", top_k=3)
    assert len(results) >= 2
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_source_and_metadata_roundtrip():
    """source and metadata survive store/retrieve."""
    backend = _make_backend()
    meta = {"author": "test", "page": 42}
    backend.store(
        "content with metadata",
        source="paper.pdf",
        metadata=meta,
    )
    results = backend.retrieve("content metadata")
    assert len(results) >= 1
    assert results[0].source == "paper.pdf"
    assert results[0].metadata["author"] == "test"
    assert results[0].metadata["page"] == 42


def test_event_bus_store():
    """store() publishes MEMORY_STORE event."""
    bus = EventBus(record_history=True)
    backend = _make_backend()

    import openjarvis.tools.storage.faiss_backend as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        backend.store("event test document")
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_STORE]
        assert len(events) == 1
        assert events[0].data["backend"] == "faiss"
        assert "doc_id" in events[0].data
    finally:
        mod.get_event_bus = original


def test_event_bus_retrieve():
    """retrieve() publishes MEMORY_RETRIEVE event."""
    bus = EventBus(record_history=True)
    backend = _make_backend()
    backend.store("searchable content for events")

    import openjarvis.tools.storage.faiss_backend as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        backend.retrieve("searchable")
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_RETRIEVE]
        assert len(events) == 1
        assert events[0].data["backend"] == "faiss"
        assert events[0].data["num_results"] >= 0
    finally:
        mod.get_event_bus = original
