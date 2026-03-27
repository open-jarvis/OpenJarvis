"""ColBERTv2 late interaction memory backend.

Uses ColBERT's token-level embeddings with MaxSim scoring for
high-quality semantic retrieval.  All data lives in memory — there is
no persistence across restarts.

Requires the ``colbert-ai`` and ``torch`` packages::

    pip install colbert-ai torch
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

try:
    import torch  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "PyTorch is required for the ColBERT memory backend. "
        "Install it with:\n\n"
        "    pip install torch\n"
    ) from exc

try:
    from colbert.modeling.checkpoint import Checkpoint  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "The 'colbert-ai' package is required for the ColBERT "
        "memory backend. Install it with:\n\n"
        "    pip install colbert-ai\n"
    ) from exc

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult


@MemoryRegistry.register("colbert")
class ColBERTMemory(MemoryBackend):
    """In-memory ColBERTv2 late interaction retrieval backend.

    Encodes queries and documents into token-level embeddings using a
    ColBERT checkpoint, then scores via MaxSim (for each query token,
    take the maximum cosine similarity across all document tokens and
    sum the results).

    The checkpoint is lazily loaded on first use to avoid heavy model
    loading during import or instantiation.
    """

    backend_id: str = "colbert"

    def __init__(
        self,
        *,
        checkpoint: str = "colbert-ir/colbertv2.0",
        device: str = "cpu",
    ) -> None:
        self._checkpoint_name = checkpoint
        self._device = device

        # id -> (content, source, metadata)
        self._documents: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
        # id -> token-level embedding tensor
        self._embeddings: Dict[str, Any] = {}

        self._checkpoint_loaded: bool = False
        self._checkpoint_obj: Any = None

    # -- lazy checkpoint loading --------------------------------------------

    def _load_checkpoint(self) -> None:
        """Load the ColBERT checkpoint on first use."""
        if self._checkpoint_loaded:
            return

        from colbert.infra import ColBERTConfig
        from colbert.modeling.checkpoint import (
            Checkpoint as _Checkpoint,
        )

        cfg = ColBERTConfig(
            doc_maxlen=512,
            query_maxlen=64,
        )
        self._checkpoint_obj = _Checkpoint(
            self._checkpoint_name,
            colbert_config=cfg,
        )
        self._checkpoint_loaded = True

    # -- encoding -----------------------------------------------------------

    def _encode(self, text: str) -> Any:
        """Encode *text* to token-level embeddings.

        Returns a 2-D ``torch.Tensor`` of shape
        ``(num_tokens, embedding_dim)``.
        """
        self._load_checkpoint()
        embs = self._checkpoint_obj.queryFromText([text])
        # queryFromText returns (batch, tokens, dim) — squeeze batch
        return embs[0]

    # -- MaxSim scoring -----------------------------------------------------

    @staticmethod
    def _maxsim(
        query_embs: Any,
        doc_embs: Any,
    ) -> float:
        """Compute the ColBERT MaxSim score.

        For each query token embedding, find the maximum cosine
        similarity with any document token embedding, then sum
        across all query tokens.

        Parameters
        ----------
        query_embs:
            Tensor of shape ``(Q, D)`` — Q query tokens.
        doc_embs:
            Tensor of shape ``(N, D)`` — N document tokens.

        Returns
        -------
        float
            The late interaction score (higher is better).
        """
        import torch as _torch

        # Normalize to unit vectors for cosine similarity
        q_norm = _torch.nn.functional.normalize(
            query_embs.float(),
            dim=-1,
        )
        d_norm = _torch.nn.functional.normalize(
            doc_embs.float(),
            dim=-1,
        )

        # (Q, D) x (D, N) -> (Q, N) cosine similarity matrix
        sim = _torch.matmul(q_norm, d_norm.T)

        # Max similarity per query token, then sum
        return float(sim.max(dim=-1).values.sum())

    # -- ABC implementation -------------------------------------------------

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        doc_id = uuid.uuid4().hex
        self._documents[doc_id] = (
            content,
            source,
            metadata or {},
        )
        self._embeddings[doc_id] = self._encode(content)

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_STORE,
            {
                "backend": self.backend_id,
                "doc_id": doc_id,
                "source": source,
            },
        )
        return doc_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Search for *query* and return the top-k results."""
        if not query.strip() or not self._documents:
            bus = get_event_bus()
            bus.publish(
                EventType.MEMORY_RETRIEVE,
                {
                    "backend": self.backend_id,
                    "query": query,
                    "num_results": 0,
                },
            )
            return []

        query_embs = self._encode(query)

        scored: List[Tuple[str, float]] = []
        for doc_id, doc_embs in self._embeddings.items():
            score = self._maxsim(query_embs, doc_embs)
            scored.append((doc_id, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)

        results: List[RetrievalResult] = []
        for doc_id, score in scored[:top_k]:
            content, source, metadata = self._documents[doc_id]
            results.append(
                RetrievalResult(
                    content=content,
                    score=score,
                    source=source,
                    metadata=dict(metadata),
                )
            )

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_RETRIEVE,
            {
                "backend": self.backend_id,
                "query": query,
                "num_results": len(results),
            },
        )
        return results

    def delete(self, doc_id: str) -> bool:
        """Delete a document by id. Return ``True`` if it existed."""
        if doc_id not in self._documents:
            return False
        del self._documents[doc_id]
        del self._embeddings[doc_id]
        return True

    def clear(self) -> None:
        """Remove all stored documents."""
        self._documents.clear()
        self._embeddings.clear()

    # -- helpers ------------------------------------------------------------

    def count(self) -> int:
        """Return the number of stored documents."""
        return len(self._documents)


__all__ = ["ColBERTMemory"]
