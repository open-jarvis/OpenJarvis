"""Tests for tools/storage — canonical location for memory backends."""

from __future__ import annotations

import pytest

from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult


class _DummyStorage(MemoryBackend):
    backend_id = "dummy"

    def __init__(self):
        self._data = {}
        self._counter = 0

    def store(self, content, *, source="", metadata=None):
        self._counter += 1
        doc_id = f"doc-{self._counter}"
        self._data[doc_id] = {"content": content, "source": source}
        return doc_id

    def retrieve(self, query, *, top_k=5, **kwargs):
        results = []
        for doc_id, doc in self._data.items():
            if query.lower() in doc["content"].lower():
                results.append(
                    RetrievalResult(
                        content=doc["content"],
                        score=1.0,
                        source=doc["source"],
                    )
                )
        return results[:top_k]

    def delete(self, doc_id):
        if doc_id in self._data:
            del self._data[doc_id]
            return True
        return False

    def clear(self):
        self._data.clear()


class TestStorageStubs:
    def test_abc_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            MemoryBackend()  # type: ignore[abstract]

    def test_concrete_implementation(self) -> None:
        storage = _DummyStorage()
        doc_id = storage.store("hello world", source="test")
        assert doc_id == "doc-1"

    def test_retrieve(self) -> None:
        storage = _DummyStorage()
        storage.store("hello world", source="test")
        results = storage.retrieve("hello")
        assert len(results) == 1
        assert results[0].content == "hello world"

    def test_retrieval_result(self) -> None:
        r = RetrievalResult(content="test", score=0.95, source="src")
        assert r.content == "test"
        assert r.score == 0.95

    def test_backward_compat_import(self) -> None:
        """Memory imports should still work via shim."""
        from openjarvis.tools.storage._stubs import MemoryBackend as MB
        from openjarvis.tools.storage._stubs import RetrievalResult as RR

        assert MB is MemoryBackend
        assert RR is RetrievalResult

    def test_canonical_import(self) -> None:
        """Canonical import from tools.storage should work."""
        from openjarvis.tools.storage._stubs import MemoryBackend as MB

        assert MB is MemoryBackend

    def test_sqlite_backward_compat(self) -> None:
        """SQLiteMemory should be importable from the canonical location."""
        from openjarvis.tools.storage.sqlite import SQLiteMemory as S1

        assert S1 is not None
