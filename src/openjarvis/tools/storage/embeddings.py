"""Embeddings abstraction for dense retrieval backends.

Provides an ABC and a default ``SentenceTransformerEmbedder`` that wraps
the ``sentence-transformers`` library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Embedder(ABC):
    """Base class for text embedding models.

    Subclasses must implement :meth:`embed` and :meth:`dim`.
    """

    @abstractmethod
    def embed(self, texts: list[str]) -> Any:
        """Embed *texts* and return a numpy array of shape (n, dim)."""

    @abstractmethod
    def dim(self) -> int:
        """Return the dimensionality of the embedding vectors."""


class SentenceTransformerEmbedder(Embedder):
    """Embedder backed by ``sentence-transformers``.

    Parameters
    ----------
    model_name:
        HuggingFace model identifier.  Defaults to the lightweight
        ``all-MiniLM-L6-v2`` (384-dim, ~22 MB).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import (
                SentenceTransformer,
            )
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for "
                "SentenceTransformerEmbedder. Install it with: "
                "pip install sentence-transformers"
            ) from exc

        self._model = SentenceTransformer(model_name)
        self._dim: int = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> Any:
        """Return a numpy array of shape ``(len(texts), dim)``."""
        return self._model.encode(texts, convert_to_numpy=True)

    def dim(self) -> int:
        """Return the embedding dimensionality."""
        return self._dim


__all__ = ["Embedder", "SentenceTransformerEmbedder"]
