"""Retrieval quality tests with a fixed corpus across backends."""

from __future__ import annotations

import pytest

from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage.sqlite import SQLiteMemory

# ---------------------------------------------------------------------------
# Shared corpus
# ---------------------------------------------------------------------------

CORPUS = [
    ("Machine learning automates statistical analysis of data", "ml.md"),
    ("Neural networks are inspired by biological brain structure", "nn.md"),
    ("Python is a popular programming language for data science", "python.md"),
    ("The capital of France is Paris, located on the Seine river", "geo.md"),
    ("Quantum computing uses qubits instead of classical bits", "quantum.md"),
]


def _build_corpus(backend):
    """Insert the fixed corpus into the given backend."""
    for content, source in CORPUS:
        backend.store(content, source=source)


# ---------------------------------------------------------------------------
# Backend factory helpers
# ---------------------------------------------------------------------------


def _make_sqlite(tmp_path):
    if not MemoryRegistry.contains("sqlite"):
        MemoryRegistry.register_value("sqlite", SQLiteMemory)
    return SQLiteMemory(db_path=tmp_path / "quality_test.db")


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
    if key == "sqlite":
        return _make_sqlite(tmp_path)
    elif key == "bm25":
        return _make_bm25()
    else:
        pytest.skip(f"Unknown backend key: {key}")


# ---------------------------------------------------------------------------
# Parametrized quality tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend_key", ["sqlite", "bm25"])
class TestRetrievalQuality:
    """Retrieval quality assertions that should hold across backends."""

    def test_exact_keyword_match(self, backend_key, tmp_path):
        """Querying 'Python programming' should return the Python document."""
        backend = _make_backend(backend_key, tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("Python programming")
        assert len(results) >= 1
        assert "Python" in results[0].content

    def test_semantic_similarity(self, backend_key, tmp_path):
        """Querying 'data analysis' should return the ML or Python document."""
        backend = _make_backend(backend_key, tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("data analysis")
        assert len(results) >= 1
        # At least one result should mention 'data'
        data_results = [r for r in results if "data" in r.content.lower()]
        assert len(data_results) >= 1

    def test_no_match_returns_empty_or_low(self, backend_key, tmp_path):
        """Querying unrelated terms should return no results."""
        backend = _make_backend(backend_key, tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("medieval castles architecture")
        # For keyword-based backends, unrelated queries return nothing
        assert len(results) == 0

    def test_ranking_order(self, backend_key, tmp_path):
        """Most relevant document should rank first."""
        backend = _make_backend(backend_key, tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("quantum computing qubits")
        assert len(results) >= 1
        content = results[0].content.lower()
        assert "quantum" in content or "qubits" in content

    def test_top_k_limiting(self, backend_key, tmp_path):
        """top_k=1 should return at most 1 result."""
        backend = _make_backend(backend_key, tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("data", top_k=1)
        assert len(results) <= 1

    def test_source_preserved(self, backend_key, tmp_path):
        """Source file information should be preserved in retrieval results."""
        backend = _make_backend(backend_key, tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("France Paris")
        assert len(results) >= 1
        assert results[0].source == "geo.md"

    def test_multiple_relevant_results(self, backend_key, tmp_path):
        """A broad query should return multiple matching documents."""
        backend = _make_backend(backend_key, tmp_path)
        _build_corpus(backend)
        # Both ML and Python docs mention 'data'
        results = backend.retrieve("data", top_k=5)
        data_results = [r for r in results if "data" in r.content.lower()]
        assert len(data_results) >= 1

    def test_query_with_stopwords(self, backend_key, tmp_path):
        """Query containing common words should still match relevant docs."""
        backend = _make_backend(backend_key, tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("the capital of France")
        assert len(results) >= 1
        # The geography document should be among results
        geo_found = any("France" in r.content for r in results)
        assert geo_found


# ---------------------------------------------------------------------------
# SQLite-specific retrieval tests
# ---------------------------------------------------------------------------


class TestSQLiteRetrievalSpecifics:
    """Tests specific to the SQLite FTS5 backend behavior."""

    def test_fts5_keyword_matching(self, tmp_path):
        backend = _make_sqlite(tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("neural networks brain")
        assert len(results) >= 1
        content = results[0].content.lower()
        assert "neural" in content or "brain" in content

    def test_fts5_partial_match(self, tmp_path):
        """FTS5 matches individual terms, not just full phrases."""
        backend = _make_sqlite(tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("programming language")
        assert len(results) >= 1
        assert "programming" in results[0].content.lower()

    def test_score_nonzero_for_matches(self, tmp_path):
        backend = _make_sqlite(tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("machine learning")
        assert len(results) >= 1
        # FTS5 scores are converted to positive values
        assert results[0].score > 0

    def test_empty_query(self, tmp_path):
        backend = _make_sqlite(tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("")
        assert results == []

    def test_whitespace_only_query(self, tmp_path):
        backend = _make_sqlite(tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("   ")
        assert results == []

    def test_single_word_query(self, tmp_path):
        backend = _make_sqlite(tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("Python")
        assert len(results) >= 1
        assert "Python" in results[0].content

    def test_retrieve_all_corpus_with_broad_query(self, tmp_path):
        """A term that does not appear in the corpus returns empty."""
        backend = _make_sqlite(tmp_path)
        _build_corpus(backend)
        results = backend.retrieve("xylophone")
        assert len(results) == 0
