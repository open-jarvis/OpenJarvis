"""Synapse memory backend — connects to a running Synapse runtime over HTTP.

Provides both the standard ``MemoryBackend`` interface (store/retrieve/delete/clear)
and generic ``emit``/``query`` methods for arbitrary Synapse events and queries.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult


@MemoryRegistry.register("synapse")
class SynapseMemory(MemoryBackend):
    """Synapse-backed memory using the Synapse runtime HTTP API.

    The standard ``store``/``retrieve``/``delete``/``clear`` methods use
    configurable default event and query names.  For direct access to any
    Synapse event handler or named query, use :meth:`emit` and
    :meth:`query`.
    """

    backend_id: str = "synapse"

    def __init__(
        self,
        url: str = "http://localhost:8080",
        store_event: str = "store",
        retrieve_query: str = "Retrieve",
        delete_event: str = "delete",
    ) -> None:
        self._url = url
        from openjarvis._rust_bridge import get_rust_module

        _rust = get_rust_module()
        self._rust_impl = _rust.SynapseMemory(
            url, store_event, retrieve_query, delete_event,
        )

    # ------------------------------------------------------------------
    # Standard MemoryBackend interface
    # ------------------------------------------------------------------

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        meta_json = json.dumps(metadata) if metadata else None
        doc_id = self._rust_impl.store(content, source, meta_json)
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

    def delete(self, doc_id: str) -> bool:
        return self._rust_impl.delete(doc_id)

    def clear(self) -> None:
        self._rust_impl.clear()

    def count(self) -> int:
        return self._rust_impl.count()

    # ------------------------------------------------------------------
    # Generic Synapse access (any event / any query by name)
    # ------------------------------------------------------------------

    def emit(self, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger any Synapse event handler by name.

        Example::

            backend.emit(
                "learn",
                {"content": "User prefers dark mode", "source": "stated"},
            )
            backend.emit(
                "archive_session",
                {"session_id": "s1", "summary": "Discussed Rust"},
            )
        """
        raw = self._rust_impl.emit(event, json.dumps(payload))
        return json.loads(raw)

    def query(self, name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Run any named Synapse query.

        Example::

            backend.query("GetFacts", {"limit_n": 10})
            backend.query("BySource", {"source": "stated"})
            backend.query("RecentMessages", {"session_id": "sess_1"})
        """
        raw = self._rust_impl.query_raw(name, json.dumps(params or {}))
        return json.loads(raw)

    def health(self) -> Dict[str, Any]:
        """Return the Synapse runtime health status."""
        return json.loads(self._rust_impl.health())

    def status(self) -> Dict[str, Any]:
        """Return the Synapse runtime status (handlers, queries, memories)."""
        return json.loads(self._rust_impl.status())

    def inspect(self) -> Dict[str, Any]:
        """Inspect all Synapse backends — tables/collections and records."""
        return json.loads(self._rust_impl.inspect_raw())

    def ping(self) -> bool:
        """Check connectivity to the Synapse runtime."""
        return self._rust_impl.ping()

    def close(self) -> None:
        pass


__all__ = ["SynapseMemory"]
