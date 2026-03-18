"""Parametrized storage tests across all memory backends."""

from __future__ import annotations

import pytest

from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage.sqlite import SQLiteMemory

# ---------------------------------------------------------------------------
# Backend factory helpers
# ---------------------------------------------------------------------------


def _make_sqlite(tmp_path):
    if not MemoryRegistry.contains("sqlite"):
        MemoryRegistry.register_value("sqlite", SQLiteMemory)
    return SQLiteMemory(db_path=tmp_path / "test.db")


def _make_bm25():
    bm25_mod = pytest.importorskip(
        "openjarvis.tools.storage.bm25",
        exc_type=ImportError,
    )
    BM25Memory = bm25_mod.BM25Memory
    if not MemoryRegistry.contains("bm25"):
        MemoryRegistry.register_value("bm25", BM25Memory)
    return BM25Memory()


def _make_backend(key, tmp_path):
    """Create a backend instance by key, skipping if dependencies are missing."""
    if key == "sqlite":
        return _make_sqlite(tmp_path)
    elif key == "bm25":
        return _make_bm25()
    elif key == "faiss":
        mod = pytest.importorskip(
            "openjarvis.tools.storage.faiss_backend",
            exc_type=ImportError,
        )
        return mod.FAISSMemory(db_path=str(tmp_path / "faiss"))
    elif key == "colbert":
        mod = pytest.importorskip(
            "openjarvis.tools.storage.colbert_backend",
            exc_type=ImportError,
        )
        return mod.ColBERTMemory(db_path=str(tmp_path / "colbert"))
    elif key == "hybrid":
        mod = pytest.importorskip(
            "openjarvis.tools.storage.hybrid",
            exc_type=ImportError,
        )
        sqlite = _make_sqlite(tmp_path)
        bm25 = _make_bm25()
        return mod.HybridMemory(sparse=sqlite, dense=bm25)
    else:
        pytest.skip(f"Unknown backend key: {key}")


# ---------------------------------------------------------------------------
# Core backends (always available)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend_key", ["sqlite", "bm25"])
class TestStorageSuiteCore:
    """Storage operations that must pass for guaranteed-available backends."""

    def test_store_and_retrieve(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        backend.store("Python is a programming language", source="wiki.md")
        results = backend.retrieve("Python programming")
        assert len(results) >= 1
        assert "Python" in results[0].content

    def test_store_multiple_documents(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        doc_ids = []
        for i in range(10):
            doc_id = backend.store(
                f"Document number {i} about testing software",
                source=f"doc{i}.md",
            )
            doc_ids.append(doc_id)
        assert len(doc_ids) == 10
        assert len(set(doc_ids)) == 10  # all unique

    def test_retrieve_respects_top_k(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        for i in range(10):
            backend.store(f"document {i} about testing software quality")
        results = backend.retrieve("testing software", top_k=3)
        assert len(results) <= 3

    def test_delete_document(self, backend_key, tmp_path):
        if backend_key == "bm25":
            pytest.skip("Rust BM25Memory PyO3 bindings do not expose delete()")
        backend = _make_backend(backend_key, tmp_path)
        doc_id = backend.store("content to delete")
        assert backend.delete(doc_id) is True
        assert backend.delete(doc_id) is False  # already deleted

    def test_clear_all(self, backend_key, tmp_path):
        if backend_key == "bm25":
            pytest.skip("Rust BM25Memory PyO3 bindings do not expose clear()")
        backend = _make_backend(backend_key, tmp_path)
        backend.store("first document")
        backend.store("second document")
        backend.clear()
        results = backend.retrieve("first")
        assert len(results) == 0

    def test_metadata_roundtrip(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        meta = {"author": "test_user", "version": 2}
        backend.store(
            "content with metadata fields",
            source="paper.pdf",
            metadata=meta,
        )
        results = backend.retrieve("content metadata")
        assert len(results) >= 1
        assert results[0].source == "paper.pdf"
        assert results[0].metadata["author"] == "test_user"
        assert results[0].metadata["version"] == 2

    def test_empty_retrieve(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        results = backend.retrieve("anything at all")
        assert results == []

    def test_store_returns_doc_id(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        doc_id = backend.store("some content")
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

    def test_duplicate_content(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        id1 = backend.store("identical content here")
        id2 = backend.store("identical content here")
        assert id1 != id2  # different IDs even for same content

    def test_large_document(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        base = "This is a large test document about software engineering. "
        large_content = base * 200
        assert len(large_content) > 10000
        doc_id = backend.store(large_content, source="large.txt")
        assert isinstance(doc_id, str)
        results = backend.retrieve("software engineering")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Optional backends (may need extra dependencies)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend_key", ["faiss", "colbert", "hybrid"])
class TestStorageSuiteOptional:
    """Same core operations for backends that require optional dependencies."""

    def test_store_and_retrieve(self, backend_key, tmp_path):
        backend = _make_backend(backend_key, tmp_path)
        backend.store("Python is a programming language", source="wiki.md")
        results = backend.retrieve("Python programming")
        assert len(results) >= 1
        assert "Python" in results[0].content

    def test_delete_document(self, backend_key, tmp_path):
        if backend_key == "hybrid":
            pytest.skip("HybridMemory sub-backend BM25 lacks delete()")
        backend = _make_backend(backend_key, tmp_path)
        doc_id = backend.store("content to delete")
        assert backend.delete(doc_id) is True
        assert backend.delete(doc_id) is False

    def test_clear_all(self, backend_key, tmp_path):
        if backend_key == "hybrid":
            pytest.skip("HybridMemory sub-backend BM25 lacks clear()")
        backend = _make_backend(backend_key, tmp_path)
        backend.store("first document")
        backend.store("second document")
        backend.clear()
        results = backend.retrieve("first")
        assert len(results) == 0
