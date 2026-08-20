"""FAISS dense retrieval memory backend.

Uses cosine similarity via inner-product search on L2-normalised
vectors.  Requires ``faiss-cpu`` (or ``faiss-gpu``) and ``numpy``.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import faiss
except ImportError as _faiss_exc:
    raise ImportError(
        "faiss is required for FAISSMemory. Install it with: "
        "pip install faiss-cpu  (or faiss-gpu)"
    ) from _faiss_exc

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult
from openjarvis.tools.storage.embeddings import (
    Embedder,
    SentenceTransformerEmbedder,
)


@MemoryRegistry.register("faiss")
class FAISSMemory(MemoryBackend):
    """Dense retrieval backend powered by FAISS.

    Stores document embeddings in a ``faiss.IndexFlatIP`` index
    (inner-product, which equals cosine similarity when vectors
    are L2-normalised before insertion/search).
    """

    backend_id: str = "faiss"

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        if embedder is None:
            embedder = SentenceTransformerEmbedder()
        self._embedder = embedder
        self._index = faiss.IndexFlatIP(self._embedder.dim())
        self._documents: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
        self._id_map: List[str] = []
        self._deleted: Set[str] = set()

    # ------------------------------------------------------------------
    # MemoryBackend interface
    # ------------------------------------------------------------------

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Embed and store *content*, returning a unique doc id."""
        doc_id = uuid.uuid4().hex
        meta = metadata if metadata is not None else {}

        vec = self._embedder.embed([content])
        faiss.normalize_L2(vec)
        self._index.add(vec)

        self._documents[doc_id] = (content, source, meta)
        self._id_map.append(doc_id)

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
        """Embed *query* and return the top-k most similar docs."""
        if not query.strip() or self._index.ntotal == 0:
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

        vec = self._embedder.embed([query])
        faiss.normalize_L2(vec)

        # Request more results to compensate for deleted docs
        k = min(
            top_k + len(self._deleted),
            self._index.ntotal,
        )
        scores, indices = self._index.search(vec, k)

        results: List[RetrievalResult] = []
        for score, idx in zip(scores[0].tolist(), indices[0].tolist()):
            if idx < 0:
                continue
            doc_id = self._id_map[idx]
            if doc_id in self._deleted:
                continue
            content, source, meta = self._documents[doc_id]
            results.append(
                RetrievalResult(
                    content=content,
                    score=float(score),
                    source=source,
                    metadata=dict(meta),
                )
            )
            if len(results) >= top_k:
                break

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
        """Soft-delete *doc_id*.  Return True if it existed."""
        if doc_id not in self._documents or doc_id in self._deleted:
            return False
        self._deleted.add(doc_id)
        return True

    def clear(self) -> None:
        """Reset the index and all internal storage."""
        self._index.reset()
        self._documents.clear()
        self._id_map.clear()
        self._deleted.clear()


__all__ = ["FAISSMemory"]
