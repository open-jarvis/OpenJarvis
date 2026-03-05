"""BM25 memory backend — classic term-frequency retrieval."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from openjarvis._rust_bridge import get_rust_module
from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult

_rust = get_rust_module()

# rank_bm25 is only needed when Rust backend is unavailable.
BM25Okapi: Any = None
if _rust is None:
    try:
        from rank_bm25 import BM25Okapi  # type: ignore[no-redef]  # noqa: E402
    except ImportError as exc:
        raise ImportError(
            "The 'rank_bm25' package is required for the BM25 memory "
            "backend. Install it with:\n\n"
            "    pip install rank-bm25\n"
        ) from exc


def _tokenize(text: str) -> List[str]:
    """Lowercase whitespace tokenizer."""
    return text.lower().split()


@MemoryRegistry.register("bm25")
class BM25Memory(MemoryBackend):
    """In-memory BM25 (Okapi) retrieval backend.

    Uses the ``rank_bm25`` library to score documents against a query
    using the classic BM25 probabilistic ranking function.  All data
    lives in memory — there is no persistence across restarts.
    """

    backend_id: str = "bm25"

    def __init__(self) -> None:
        _r = get_rust_module()
        self._rust_impl = _r.BM25Memory() if _r else None

        # id -> (content, source, metadata)
        self._documents: Dict[
            str, Tuple[str, str, Dict[str, Any]]
        ] = {}
        self._corpus: List[List[str]] = []
        self._doc_ids: List[str] = []
        self._bm25: Optional[Any] = None

    # -- ABC implementation -------------------------------------------------

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        if self._rust_impl is not None:
            meta_json = json.dumps(metadata) if metadata else None
            doc_id = self._rust_impl.store(content, source, meta_json)
            bus = get_event_bus()
            bus.publish(EventType.MEMORY_STORE, {
                "backend": self.backend_id,
                "doc_id": doc_id,
                "source": source,
            })
            return doc_id

        doc_id = uuid.uuid4().hex
        self._documents[doc_id] = (
            content,
            source,
            metadata or {},
        )
        self._rebuild_index()

        bus = get_event_bus()
        bus.publish(EventType.MEMORY_STORE, {
            "backend": self.backend_id,
            "doc_id": doc_id,
            "source": source,
        })
        return doc_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Search for *query* and return the top-k results."""
        if self._rust_impl is not None:
            if not query.strip():
                return []
            from openjarvis._rust_bridge import retrieval_results_from_json
            results = retrieval_results_from_json(
                self._rust_impl.retrieve(query, top_k),
            )
            bus = get_event_bus()
            bus.publish(EventType.MEMORY_RETRIEVE, {
                "backend": self.backend_id,
                "query": query,
                "num_results": len(results),
            })
            return results

        if not query.strip() or self._bm25 is None:
            bus = get_event_bus()
            bus.publish(EventType.MEMORY_RETRIEVE, {
                "backend": self.backend_id,
                "query": query,
                "num_results": 0,
            })
            return []

        tokenized_query = _tokenize(query)
        query_set = set(tokenized_query)
        scores = self._bm25.get_scores(tokenized_query)

        # Pair (index, score), sort descending by score
        scored = sorted(
            enumerate(scores),
            key=lambda pair: pair[1],
            reverse=True,
        )

        results: List[RetrievalResult] = []
        for idx, score in scored[:top_k]:
            # Skip documents that share no tokens with the query.
            # We check token overlap rather than score > 0 because
            # BM25Okapi can assign IDF = 0 for terms appearing in
            # exactly half the corpus, producing a zero score even
            # when the document genuinely matches.
            if not query_set.intersection(self._corpus[idx]):
                continue
            doc_id = self._doc_ids[idx]
            content, source, metadata = self._documents[doc_id]
            results.append(RetrievalResult(
                content=content,
                score=float(score),
                source=source,
                metadata=dict(metadata),
            ))

        bus = get_event_bus()
        bus.publish(EventType.MEMORY_RETRIEVE, {
            "backend": self.backend_id,
            "query": query,
            "num_results": len(results),
        })
        return results

    def delete(self, doc_id: str) -> bool:
        """Delete a document by id. Return ``True`` if it existed."""
        if self._rust_impl is not None:
            # Rust BM25Memory doesn't expose delete; fall through to Python.
            pass
        if doc_id not in self._documents:
            return False
        del self._documents[doc_id]
        self._rebuild_index()
        return True

    def clear(self) -> None:
        """Remove all stored documents."""
        self._documents.clear()
        self._corpus.clear()
        self._doc_ids.clear()
        self._bm25 = None

    # -- helpers ------------------------------------------------------------

    def count(self) -> int:
        """Return the number of stored documents."""
        if self._rust_impl is not None:
            return self._rust_impl.count()
        return len(self._documents)

    def _rebuild_index(self) -> None:
        """Recreate the BM25 index from the current document set."""
        self._doc_ids = list(self._documents.keys())
        self._corpus = [
            _tokenize(self._documents[did][0])
            for did in self._doc_ids
        ]
        if self._corpus:
            self._bm25 = BM25Okapi(self._corpus)
        else:
            self._bm25 = None


__all__ = ["BM25Memory"]
