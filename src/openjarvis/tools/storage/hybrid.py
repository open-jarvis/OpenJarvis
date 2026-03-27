"""Hybrid memory backend — Reciprocal Rank Fusion of two retrievers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult


def reciprocal_rank_fusion(
    ranked_lists: List[List[RetrievalResult]],
    *,
    k: int = 60,
    weights: Optional[List[float]] = None,
) -> List[RetrievalResult]:
    """Fuse multiple ranked result lists using RRF.

    ``RRF_score(d) = sum(weight_i / (k + rank_i(d)))``

    Parameters
    ----------
    ranked_lists:
        Each inner list is a ranked sequence of results (best first).
    k:
        RRF constant (default 60).
    weights:
        Per-list weight (defaults to equal weighting).

    Returns
    -------
    Merged list sorted by fused score, descending.
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)

    # Map content -> (fused_score, best_result)
    scores: Dict[str, float] = {}
    best_result: Dict[str, RetrievalResult] = {}

    for weight, results in zip(weights, ranked_lists):
        for rank, result in enumerate(results):
            key = result.content
            rrf = weight / (k + rank + 1)
            scores[key] = scores.get(key, 0.0) + rrf

            # Keep the result with the highest original score
            if key not in best_result:
                best_result[key] = result

    # Build fused results
    fused = []
    for content_key, fused_score in sorted(
        scores.items(), key=lambda x: x[1], reverse=True
    ):
        original = best_result[content_key]
        fused.append(
            RetrievalResult(
                content=original.content,
                score=fused_score,
                source=original.source,
                metadata=original.metadata,
            )
        )

    return fused


@MemoryRegistry.register("hybrid")
class HybridMemory(MemoryBackend):
    """Fuses a sparse and a dense retriever via RRF.

    Stores documents in both sub-backends and merges retrieval
    results using Reciprocal Rank Fusion.
    """

    backend_id: str = "hybrid"

    def __init__(
        self,
        *,
        sparse: MemoryBackend,
        dense: MemoryBackend,
        k: int = 60,
        sparse_weight: float = 1.0,
        dense_weight: float = 1.0,
    ) -> None:
        self._sparse = sparse
        self._dense = dense
        self._k = k
        self._weights = [sparse_weight, dense_weight]
        # Track doc IDs across both backends
        self._id_map: Dict[str, str] = {}

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store in both sub-backends with the same doc id."""
        # Store in sparse first to get the id
        sparse_id = self._sparse.store(
            content,
            source=source,
            metadata=metadata,
        )
        # Store in dense — it generates its own id
        dense_id = self._dense.store(
            content,
            source=source,
            metadata=metadata,
        )
        # Map sparse_id -> dense_id so we can delete from both
        self._id_map[sparse_id] = dense_id

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_STORE,
            {
                "backend": self.backend_id,
                "doc_id": sparse_id,
                "source": source,
            },
        )
        return sparse_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Retrieve from both backends and fuse with RRF."""
        # Over-fetch for better fusion
        fetch_k = top_k * 3

        sparse_results = self._sparse.retrieve(
            query,
            top_k=fetch_k,
        )
        dense_results = self._dense.retrieve(
            query,
            top_k=fetch_k,
        )

        fused = reciprocal_rank_fusion(
            [sparse_results, dense_results],
            k=self._k,
            weights=self._weights,
        )

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_RETRIEVE,
            {
                "backend": self.backend_id,
                "query": query,
                "num_results": min(len(fused), top_k),
            },
        )

        return fused[:top_k]

    def delete(self, doc_id: str) -> bool:
        """Delete from both sub-backends."""
        sparse_ok = self._sparse.delete(doc_id)
        dense_id = self._id_map.pop(doc_id, None)
        dense_ok = False
        if dense_id is not None:
            dense_ok = self._dense.delete(dense_id)
        return sparse_ok or dense_ok

    def clear(self) -> None:
        """Clear both sub-backends."""
        self._sparse.clear()
        self._dense.clear()
        self._id_map.clear()


__all__ = ["HybridMemory", "reciprocal_rank_fusion"]
