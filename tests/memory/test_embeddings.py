"""Tests for the embeddings abstraction layer."""

from __future__ import annotations

import pytest

st = pytest.importorskip("sentence_transformers")

from friday_ai.tools.storage.embeddings import (  # noqa: E402
    Embedder,
    SentenceTransformerEmbedder,
)


@pytest.fixture()
def embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder()


def test_produces_vectors(embedder: SentenceTransformerEmbedder):
    """embed() returns a numpy array with one row per input."""
    import numpy as np

    vecs = embedder.embed(["hello world"])
    assert isinstance(vecs, np.ndarray)
    assert vecs.shape[0] == 1


def test_correct_dimension(
    embedder: SentenceTransformerEmbedder,
):
    """Embedding dimension matches the declared dim()."""
    vecs = embedder.embed(["test"])
    assert vecs.shape[1] == embedder.dim()


def test_batch(embedder: SentenceTransformerEmbedder):
    """Batch of texts produces matching number of vectors."""
    texts = ["one", "two", "three"]
    vecs = embedder.embed(texts)
    assert vecs.shape[0] == 3
    assert vecs.shape[1] == embedder.dim()


def test_empty_input(embedder: SentenceTransformerEmbedder):
    """Empty list produces an empty array."""
    import numpy as np

    vecs = embedder.embed([])
    assert isinstance(vecs, np.ndarray)
    assert vecs.shape[0] == 0


def test_missing_dep(monkeypatch: pytest.MonkeyPatch):
    """Import error is raised with a helpful message."""
    import builtins

    real_import = builtins.__import__

    def _block_st(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "sentence_transformers":
            raise ImportError("mocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_st)
    with pytest.raises(ImportError, match="sentence-transformers"):
        SentenceTransformerEmbedder()


def test_embedder_abc_cannot_instantiate():
    """Embedder ABC cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Embedder()  # type: ignore[abstract]
