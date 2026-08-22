"""Mixedbread agentic retrieval memory backend.

Stores documents in a Mixedbread store and retrieves through the
`toast-1 <https://www.mixedbread.com/blog/toast-1>`_ search agent, which
handles query decomposition, evidence gathering and result ranking
server-side.  Requires the ``mixedbread`` SDK and an API key
(``MXBAI_API_KEY``).

Unlike the local backends, this one sends stored content and queries to
the Mixedbread cloud API — it must only ever be enabled by explicit
opt-in (``[tools.storage] default_backend = "mixedbread"``), never as a
silent fallback.
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any, Dict, List, Optional

try:
    from mixedbread import ConflictError, Mixedbread, NotFoundError
except ImportError as _mxbai_exc:
    raise ImportError(
        "mixedbread is required for MixedbreadMemory. Install it with: "
        "pip install mixedbread"
    ) from _mxbai_exc

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult

DEFAULT_STORE_NAME = "openjarvis-memory"

API_KEY_MISSING_HINT = (
    "MixedbreadMemory requires an API key. Set the MXBAI_API_KEY "
    "environment variable (get a key at https://www.mixedbread.com) or "
    "pass api_key= explicitly."
)


def resolve_store_id(client: Any, store_name: str) -> str:
    """Find-or-create the store *store_name* and return its id.

    A concurrent process can create the store between our retrieve and
    create; a create that 409s falls back to retrieving the winner's
    store.  In-process races are the caller's concern (hold a lock).
    """
    try:
        store = client.stores.retrieve(store_name)
    except NotFoundError:
        try:
            store = client.stores.create(name=store_name)
        except ConflictError:
            store = client.stores.retrieve(store_name)
    return store.id


@MemoryRegistry.register("mixedbread")
class MixedbreadMemory(MemoryBackend):
    """Cloud retrieval backend powered by Mixedbread's toast-1 search agent.

    Documents are uploaded as files to a named Mixedbread store (created
    on first use); retrieval calls the stores search endpoint with
    agentic mode enabled, so multi-hop query decomposition and ranking
    happen inside toast-1 rather than in the calling model's context.
    """

    backend_id: str = "mixedbread"

    def __init__(
        self,
        *,
        store_name: str = DEFAULT_STORE_NAME,
        api_key: Optional[str] = None,
        agentic: bool = True,
        wait_for_indexing: bool = False,
        client: Any = None,
        db_path: Any = None,
    ) -> None:
        """Create a backend bound to one Mixedbread store.

        ``db_path`` is accepted and ignored: `SystemBuilder` and the CLI
        pass it to every backend via ``MemoryRegistry.create``, but this
        backend persists remotely.  ``client`` allows injecting a
        pre-built (or fake) ``Mixedbread`` client, primarily for tests.
        ``wait_for_indexing`` makes ``store()`` block until the uploaded
        document is indexed and searchable; the default returns as soon
        as the upload is accepted, so an immediate ``retrieve()`` may
        not yet see it.
        """
        del db_path
        self._owns_client = client is None
        if client is None:
            if not (api_key or os.environ.get("MXBAI_API_KEY")):
                raise ValueError(API_KEY_MISSING_HINT)
            client = Mixedbread(api_key=api_key)
        self._client = client
        self._store_name = store_name
        self._agentic = agentic
        self._wait_for_indexing = wait_for_indexing
        self._store_id: Optional[str] = None
        self._store_lock = threading.Lock()
        self._closed = False

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
        """Upload *content* to the store and return the store-file id."""
        meta = dict(metadata) if metadata is not None else {}
        meta.setdefault("source", source)
        filename = f"openjarvis-{uuid.uuid4().hex}.md"

        upload = (
            self._client.stores.files.upload_and_poll
            if (self._wait_for_indexing)
            else self._client.stores.files.upload
        )
        store_file = upload(
            store_identifier=self._ensure_store(),
            file=(filename, content.encode("utf-8")),
            metadata=meta,
        )
        doc_id = store_file.id

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
        """Run an agentic search for *query* and return the top-k chunks."""
        if not query.strip():
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

        response = self._client.stores.search(
            query=query,
            store_identifiers=[self._ensure_store()],
            top_k=top_k,
            search_options={
                "agentic": self._agentic,
                "return_metadata": True,
            },
        )

        results: List[RetrievalResult] = []
        for chunk in response.data:
            # Stores can hold image/audio/video chunks with no text body;
            # a text-only memory interface has nothing to return for those.
            text = getattr(chunk, "text", None)
            if not text:
                continue
            file_meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
            results.append(
                RetrievalResult(
                    content=text,
                    score=float(chunk.score),
                    source=str(file_meta.get("source") or chunk.filename),
                    metadata={
                        **file_meta,
                        "file_id": chunk.file_id,
                        "filename": chunk.filename,
                        "chunk_index": chunk.chunk_index,
                    },
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
        """Delete the store-file *doc_id*.  Return True if it existed."""
        try:
            self._client.stores.files.delete(
                doc_id,
                store_identifier=self._ensure_store(),
            )
        except NotFoundError:
            return False
        return True

    def clear(self) -> None:
        """Delete the remote store; it is recreated lazily on next use."""
        with self._store_lock:
            try:
                self._client.stores.delete(self._store_id or self._store_name)
            except NotFoundError:
                pass
            self._store_id = None

    def close(self) -> None:
        """Close the SDK client when this backend created it."""
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "MixedbreadMemory":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_store(self) -> str:
        """Resolve the configured store name to an id, creating it if absent.

        Locked: concurrent first calls would otherwise all see the store
        missing and each create one.  A concurrent *process* can still
        win the same race, so a create that conflicts falls back to
        retrieving the store the other process made.
        """
        if self._store_id is None:
            with self._store_lock:
                if self._store_id is None:
                    self._store_id = resolve_store_id(self._client, self._store_name)
        return self._store_id


__all__ = [
    "MixedbreadMemory",
    "DEFAULT_STORE_NAME",
    "API_KEY_MISSING_HINT",
    "resolve_store_id",
]
