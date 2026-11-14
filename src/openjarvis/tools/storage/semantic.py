"""Semantic fact ranking for memory context injection.

Ranks durable facts by embedding similarity against the user query, using a
local Ollama embedding model (default ``nomic-embed-text``) — the
semantic-recall pattern of local-first assistants. When the embedder is
unavailable, callers keep the keyword/recency-only selection unchanged.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Optional, Sequence

from openjarvis.tools.storage.embeddings import Embedder

logger = logging.getLogger(__name__)


class SemanticFactRanker:
    """Rank texts by cosine similarity to a query via a local embedder.

    ``OllamaEmbedder`` L2-normalizes rows, so dot product == cosine.
    Embeddings are cached per text: across turns only the query is embedded
    once the fact store is warm.
    """

    def __init__(self, embedder: Embedder, *, cache_size: int = 1024) -> None:
        self._embedder = embedder
        self._cache_size = max(1, cache_size)
        self._cache: dict[str, Any] = {}

    def _vector(self, text: str) -> Any:
        vector = self._cache.get(text)
        if vector is not None:
            return vector
        vector = self._embedder.embed([text])[0]
        if len(self._cache) >= self._cache_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[text] = vector
        return vector

    def rank(self, query: str, texts: Sequence[str]) -> List[float]:
        """Return cosine similarities between *query* and each of *texts*."""
        if not texts:
            return []
        import numpy as np

        query_vector = self._embedder.embed([query])[0]
        matrix = np.asarray(
            [self._vector(text) for text in texts],
            dtype=np.float32,
        )
        scores = np.asarray(matrix @ query_vector, dtype=np.float64)
        return list(scores.tolist())


def build_semantic_ranker(config: Any) -> Optional[SemanticFactRanker]:
    """Build a ranker from ``[memory]`` config, or ``None`` when unavailable.

    Enabled by ``memory.semantic_enabled`` (or ``JARVIS_SEMANTIC_MEMORY=1``).
    The embedding model comes from ``JARVIS_EMBED_MODEL``, then
    ``memory.embedding_model``. Never raises — a missing model or unreachable
    Ollama server simply keeps memory injection keyword/recency-based.
    """
    memory = getattr(config, "memory", None)
    if memory is None:
        return None
    enabled = os.environ.get("JARVIS_SEMANTIC_MEMORY")
    if enabled is None:
        enabled_flag = getattr(memory, "semantic_enabled", False)
    else:
        enabled_flag = enabled.strip().lower() in ("1", "true", "yes", "on")
    if not enabled_flag:
        return None

    model = os.environ.get("JARVIS_EMBED_MODEL") or getattr(
        memory, "embedding_model", "nomic-embed-text"
    )
    try:
        from openjarvis.tools.storage.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(model=model)
        embedder.dim()  # probe: confirms the model exists on the server
        return SemanticFactRanker(embedder)
    except Exception as exc:  # noqa: BLE001 — semantic memory is best-effort
        logger.debug("Semantic memory ranker unavailable: %s", exc)
        return None


__all__ = ["SemanticFactRanker", "build_semantic_ranker"]
