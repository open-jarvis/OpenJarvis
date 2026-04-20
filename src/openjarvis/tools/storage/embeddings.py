"""Embeddings abstraction for dense retrieval backends."""

from __future__ import annotations

import concurrent.futures
from abc import ABC, abstractmethod
from typing import Any, List, Optional


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


class OllamaEmbedder(Embedder):
    """Embedder backed by an Ollama server's ``/api/embed`` endpoint.

    Sends batches in parallel (up to ``max_parallel``) since Ollama
    serializes items within a single HTTP request but happily serves
    multiple concurrent connections.

    Parameters
    ----------
    model:
        Ollama model tag; defaults to ``nomic-embed-text`` (768-dim).
    base_url:
        Ollama server base URL.  Defaults to ``http://localhost:11434``.
    batch_size:
        Items per HTTP request.  Tuned for Ollama — larger batches help
        throughput but increase memory on the server.
    max_parallel:
        How many concurrent HTTP requests to issue.  Ollama CPU/GPU
        saturation is typically hit around 8.
    timeout_s:
        Per-request timeout.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        *,
        batch_size: int = 16,
        max_parallel: int = 8,
        timeout_s: float = 120.0,
    ) -> None:
        import httpx  # local import to keep module light if unused

        self._model = model
        self._base_url = base_url.rstrip("/")
        self._batch_size = max(1, batch_size)
        self._max_parallel = max(1, max_parallel)
        self._timeout_s = timeout_s
        self._httpx = httpx
        self._dim_cached: Optional[int] = None

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Issue one HTTP request for ``texts`` and return raw vectors."""
        resp = self._httpx.post(
            f"{self._base_url}/api/embed",
            json={"model": self._model, "input": texts},
            timeout=self._timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings")
        if not embeddings:
            raise RuntimeError(
                f"Ollama returned no embeddings for model {self._model!r}. "
                f"Response keys: {list(data.keys())}"
            )
        return embeddings

    def embed(self, texts: list[str]) -> Any:
        """Return a numpy array of shape ``(len(texts), dim)``.

        Float32, L2-normalized per row so callers can use dot-product
        as cosine similarity. Empty input → shape ``(0, dim)``.
        """
        import numpy as np

        if not texts:
            return np.zeros((0, self.dim()), dtype=np.float32)

        # Partition into batches
        batches = [
            texts[i : i + self._batch_size]
            for i in range(0, len(texts), self._batch_size)
        ]

        # Fan out batches concurrently
        results: List[Optional[List[List[float]]]] = [None] * len(batches)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self._max_parallel, len(batches)),
        ) as pool:
            future_to_idx = {
                pool.submit(self._embed_batch, batch): i
                for i, batch in enumerate(batches)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()

        # Stitch back in order and stack
        flat: List[List[float]] = []
        for batch_result in results:
            assert batch_result is not None  # all futures returned
            flat.extend(batch_result)

        arr = np.asarray(flat, dtype=np.float32)
        # L2-normalize rows; guard against zero vectors
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        arr = arr / norms

        if self._dim_cached is None:
            self._dim_cached = int(arr.shape[1])
        return arr

    def dim(self) -> int:
        """Return the embedding dimensionality (probes the server on first call)."""
        if self._dim_cached is None:
            # Probe with a single trivial input
            vecs = self._embed_batch(["probe"])
            self._dim_cached = len(vecs[0])
        return self._dim_cached


__all__ = ["Embedder", "OllamaEmbedder", "SentenceTransformerEmbedder"]
