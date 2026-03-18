"""Tests for the Hybrid RRF memory backend."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult
from openjarvis.tools.storage.hybrid import (
    HybridMemory,
    reciprocal_rank_fusion,
)

# -- Fake in-memory backend for testing -----------------------------------


class _FakeBackend(MemoryBackend):
    """Minimal in-memory backend for testing hybrid logic."""

    backend_id: str = "fake"

    def __init__(self) -> None:
        self._docs: Dict[str, tuple] = {}

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        doc_id = uuid.uuid4().hex
        self._docs[doc_id] = (content, source, metadata or {})
        return doc_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        # Simple substring match with position-based scoring
        results = []
        for doc_id, (content, source, meta) in self._docs.items():
            if query.lower() in content.lower():
                results.append(
                    RetrievalResult(
                        content=content,
                        score=1.0,
                        source=source,
                        metadata=meta,
                    )
                )
        return results[:top_k]

    def delete(self, doc_id: str) -> bool:
        if doc_id in self._docs:
            del self._docs[doc_id]
            return True
        return False

    def clear(self) -> None:
        self._docs.clear()


def _make_hybrid() -> HybridMemory:
    """Create a HybridMemory with two fake backends."""
    if not MemoryRegistry.contains("hybrid"):
        MemoryRegistry.register_value("hybrid", HybridMemory)
    sparse = _FakeBackend()
    dense = _FakeBackend()
    return HybridMemory(sparse=sparse, dense=dense)


# -- RRF unit tests -------------------------------------------------------


def test_rrf_scoring_correctness():
    """Verify RRF formula: score = sum(w / (k + rank + 1))."""
    list1 = [
        RetrievalResult(content="A", score=10.0),
        RetrievalResult(content="B", score=5.0),
    ]
    list2 = [
        RetrievalResult(content="B", score=8.0),
        RetrievalResult(content="C", score=3.0),
    ]
    fused = reciprocal_rank_fusion([list1, list2], k=60)

    scores = {r.content: r.score for r in fused}
    # A: only in list1 at rank 0 → 1/(60+1) ≈ 0.01639
    assert abs(scores["A"] - 1 / 61) < 1e-6
    # B: list1 rank 1 + list2 rank 0 → 1/(60+2) + 1/(60+1)
    expected_b = 1 / 62 + 1 / 61
    assert abs(scores["B"] - expected_b) < 1e-6
    # C: only in list2 at rank 1 → 1/(60+2)
    assert abs(scores["C"] - 1 / 62) < 1e-6
    # B should be ranked first (appears in both lists)
    assert fused[0].content == "B"


def test_rrf_with_disjoint_results():
    """Two lists with no overlap."""
    list1 = [RetrievalResult(content="X", score=1.0)]
    list2 = [RetrievalResult(content="Y", score=1.0)]
    fused = reciprocal_rank_fusion([list1, list2], k=60)
    contents = {r.content for r in fused}
    assert contents == {"X", "Y"}
    # Equal RRF scores (both at rank 0 in their list)
    assert abs(fused[0].score - fused[1].score) < 1e-6


def test_rrf_with_overlapping_results():
    """Document appearing in both lists gets higher fused score."""
    shared = RetrievalResult(content="shared", score=5.0)
    unique = RetrievalResult(content="unique", score=10.0)
    list1 = [shared, unique]
    list2 = [RetrievalResult(content="shared", score=3.0)]
    fused = reciprocal_rank_fusion([list1, list2], k=60)
    scores = {r.content: r.score for r in fused}
    assert scores["shared"] > scores["unique"]


def test_rrf_custom_weights():
    """Weights affect the contribution of each list."""
    list1 = [RetrievalResult(content="A", score=1.0)]
    list2 = [RetrievalResult(content="B", score=1.0)]
    fused = reciprocal_rank_fusion(
        [list1, list2],
        k=60,
        weights=[2.0, 1.0],
    )
    scores = {r.content: r.score for r in fused}
    # A has weight 2, B has weight 1, both at rank 0
    assert scores["A"] > scores["B"]


# -- HybridMemory integration tests ---------------------------------------


def test_registration():
    MemoryRegistry.register_value("hybrid", HybridMemory)
    assert MemoryRegistry.contains("hybrid")


def test_store_delegates_to_both():
    hybrid = _make_hybrid()
    doc_id = hybrid.store("test content", source="test.txt")
    assert isinstance(doc_id, str)
    # Both sub-backends should have the content
    sparse_results = hybrid._sparse.retrieve("test content")
    dense_results = hybrid._dense.retrieve("test content")
    assert len(sparse_results) >= 1
    assert len(dense_results) >= 1


def test_retrieve_fuses_results():
    hybrid = _make_hybrid()
    hybrid.store("machine learning algorithms")
    hybrid.store("cooking recipes for dinner")
    results = hybrid.retrieve("machine learning")
    assert len(results) >= 1
    assert "machine" in results[0].content.lower()


def test_retrieve_top_k():
    hybrid = _make_hybrid()
    for i in range(10):
        hybrid.store(f"document {i} about testing topic")
    results = hybrid.retrieve("testing", top_k=3)
    assert len(results) <= 3


def test_delete_from_both():
    hybrid = _make_hybrid()
    doc_id = hybrid.store("deletable content")
    assert hybrid.delete(doc_id) is True
    # Should be gone from sparse
    assert len(hybrid._sparse.retrieve("deletable")) == 0


def test_clear_both():
    hybrid = _make_hybrid()
    hybrid.store("doc one about topics")
    hybrid.store("doc two about topics")
    hybrid.clear()
    assert len(hybrid._sparse.retrieve("topics")) == 0
    assert len(hybrid._dense.retrieve("topics")) == 0


def test_event_bus_store():
    bus = EventBus(record_history=True)
    hybrid = _make_hybrid()
    import openjarvis.tools.storage.hybrid as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        hybrid.store("event test content")
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_STORE]
        assert len(events) >= 1
        assert any(e.data.get("backend") == "hybrid" for e in events)
    finally:
        mod.get_event_bus = original


def test_event_bus_retrieve():
    bus = EventBus(record_history=True)
    hybrid = _make_hybrid()
    hybrid.store("retrievable content here")
    import openjarvis.tools.storage.hybrid as mod

    original = mod.get_event_bus
    mod.get_event_bus = lambda: bus
    try:
        hybrid.retrieve("retrievable")
        events = [e for e in bus.history if e.event_type == EventType.MEMORY_RETRIEVE]
        assert len(events) >= 1
        assert any(e.data.get("backend") == "hybrid" for e in events)
    finally:
        mod.get_event_bus = original
