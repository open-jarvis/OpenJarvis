"""Toast-1 agentic retrieval over a mirrored Deep Research knowledge base.

Drop-in alternative to :class:`~openjarvis.connectors.hybrid_search.HybridSearch`
for the research loop: the same ``search()`` signature and ``SearchHit``
results, but ranking is delegated to Mixedbread's `toast-1
<https://www.mixedbread.com/blog/toast-1>`_ search agent, which performs
query decomposition, evidence gathering and ranking server-side.

The knowledge base stays local and canonical: :class:`MixedbreadKnowledgeSync`
mirrors ``knowledge_chunks`` rows into a Mixedbread store, keyed by
``external_id = chunk_id`` so every remote result maps back to its local
row.  ``search()`` then hydrates hits from SQLite — titles, timestamps,
participants, deep links and thread context all come from the local store,
so citations are exactly as rich as hybrid search produces.  Structured
filters (person / time range / sources) are applied to the hydrated rows
with the same SQL fragments hybrid search uses.

This is a cloud opt-in (``[deep_research] retrieval = "mixedbread"``):
mirrored content and queries are sent to the Mixedbread API.  Any API
failure falls back to the local :class:`HybridSearch` when one is
provided, so research keeps working offline.

The ``mixedbread`` SDK is imported lazily so this module (and the
``build_research_search`` factory) can always be imported.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator, List, Optional, Sequence, Tuple

from openjarvis.connectors.hybrid_search import (
    HybridSearch,
    SearchHit,
    _parse_participants,
    _snippet,
)
from openjarvis.connectors.store import KnowledgeStore

logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_STORE = "openjarvis-knowledge"
MIRROR_METADATA_KEY = "openjarvis_knowledge_mirror"


def _build_client(api_key: Optional[str]) -> Any:
    """Construct a ``Mixedbread`` client, with an actionable key error."""
    from openjarvis.tools.storage.mixedbread_backend import (
        API_KEY_MISSING_HINT,
        Mixedbread,
    )

    if not (api_key or os.environ.get("MXBAI_API_KEY")):
        raise ValueError(API_KEY_MISSING_HINT)
    return Mixedbread(api_key=api_key)


@dataclass(slots=True)
class SyncReport:
    """Outcome of one :meth:`MixedbreadKnowledgeSync.sync` run."""

    uploaded: int = 0
    failed: int = 0
    deleted: int = 0
    delete_failed: int = 0
    total: int = 0
    dry_run: bool = False


class MixedbreadKnowledgeSync:
    """Mirror local ``knowledge_chunks`` into a Mixedbread store.

    Uploads are keyed by ``external_id = chunk_id`` with ``overwrite=True``,
    so re-running sync is idempotent server-side and needs no local
    bookkeeping.  Soft-deleted chunks are never uploaded.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        store_name: str = DEFAULT_KNOWLEDGE_STORE,
        api_key: Optional[str] = None,
        client: Any = None,
        max_workers: int = 8,
    ) -> None:
        self._store = store
        self._store_name = store_name
        self._owns_client = client is None
        self._client = client if client is not None else _build_client(api_key)
        self._max_workers = int(max_workers)
        self._closed = False

    def sync(self, *, dry_run: bool = False) -> SyncReport:
        """Mirror live chunks and remove stale mirrored cloud files."""
        rows = self._store.list_live_chunks()
        report = SyncReport(total=len(rows), dry_run=dry_run)
        if dry_run:
            return report

        from openjarvis.tools.storage.mixedbread_backend import resolve_store_id

        store_id = resolve_store_id(self._client, self._store_name)

        def _push(row: Any) -> bool:
            try:
                self._client.stores.files.upload(
                    store_identifier=store_id,
                    file=(f"{row['id']}.md", _chunk_document(row).encode("utf-8")),
                    metadata={
                        "source": row["source"] or "",
                        "title": row["title"] or "",
                        "doc_id": row["doc_id"] or "",
                        MIRROR_METADATA_KEY: True,
                    },
                    external_id=row["id"],
                    overwrite=True,
                )
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("mixedbread sync: chunk %s failed (%s)", row["id"], exc)
                return False

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            outcomes = list(pool.map(_push, rows))
        report.uploaded = sum(outcomes)
        report.failed = len(outcomes) - report.uploaded

        live_ids = {row["id"] for row in rows}
        try:
            remote_files = list(self._iter_mirrored_files(store_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("mixedbread sync: could not list remote files (%s)", exc)
            report.delete_failed += 1
            return report

        for remote in remote_files:
            external_id = str(getattr(remote, "external_id", "") or "")
            if not external_id or external_id in live_ids:
                continue
            try:
                self._client.stores.files.delete(
                    remote.id,
                    store_identifier=store_id,
                )
                report.deleted += 1
            except Exception as exc:  # noqa: BLE001
                report.delete_failed += 1
                logger.warning(
                    "mixedbread sync: stale chunk %s could not be deleted (%s)",
                    external_id,
                    exc,
                )
        return report

    def _iter_mirrored_files(self, store_id: str) -> Iterator[Any]:
        """Yield this integration's files across all SDK result pages."""
        after: Optional[str] = None
        while True:
            kwargs: dict[str, Any] = {
                "store_identifier": store_id,
                "limit": 100,
            }
            if after is not None:
                kwargs["after"] = after
            page = self._client.stores.files.list(**kwargs)
            for remote in getattr(page, "data", ()):
                metadata = getattr(remote, "metadata", None)
                if (
                    isinstance(metadata, dict)
                    and metadata.get(MIRROR_METADATA_KEY) is True
                ):
                    yield remote

            pagination = getattr(page, "pagination", None)
            if not pagination or not getattr(pagination, "has_more", False):
                return
            next_cursor = getattr(pagination, "last_cursor", None)
            if not next_cursor or next_cursor == after:
                raise RuntimeError("Mixedbread file listing returned an invalid cursor")
            after = str(next_cursor)

    def close(self) -> None:
        """Close the SDK client when this instance created it."""
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "MixedbreadKnowledgeSync":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _chunk_document(row: Any) -> str:
    """Render one knowledge chunk as a small markdown document.

    The header gives toast-1 provenance (who/when/where) to reason over;
    hydration back from SQLite means nothing here needs to round-trip.
    """
    lines: List[str] = []
    if row["title"]:
        lines.append(f"# {row['title']}")
    for label, key in (
        ("Source", "source"),
        ("Author", "author"),
        ("Date", "timestamp"),
    ):
        if row[key]:
            lines.append(f"{label}: {row[key]}")
    if lines:
        lines.append("")
    lines.append(row["content"] or "")
    return "\n".join(lines)


class MixedbreadSearch:
    """``HybridSearch``-compatible retrieval backed by toast-1.

    Exposes ``_store`` because ``ResearchAgent._resolve_available_sources``
    reads it to list connected sources in the planner prompt.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        store_name: str = DEFAULT_KNOWLEDGE_STORE,
        api_key: Optional[str] = None,
        agentic: bool = True,
        client: Any = None,
        fallback: Optional[HybridSearch] = None,
        overfetch: int = 3,
    ) -> None:
        self._store = store
        self._store_name = store_name
        self._agentic = agentic
        self._owns_client = client is None
        self._client = client if client is not None else _build_client(api_key)
        self._fallback = fallback
        self._overfetch = max(1, int(overfetch))
        # Reused for its filter-SQL builder and thread-context enrichment,
        # not for ranking.
        self._helper = HybridSearch(store, None)
        self._store_id: Optional[str] = None
        self._store_lock = threading.Lock()
        self._closed = False

    def search(
        self,
        query: str,
        *,
        person: Optional[str] = None,
        time_range: Optional[Tuple[Optional[datetime], Optional[datetime]]] = None,
        sources: Optional[Sequence[str]] = None,
        limit: int = 20,
    ) -> List[SearchHit]:
        """Agentic search, hydrated and filtered against the local store.

        Empty queries are pure metadata filters — those need SQL, not a
        search agent, so they go straight to the local fallback.
        """
        if not query.strip():
            if self._fallback is not None:
                return self._fallback.search(
                    query,
                    person=person,
                    time_range=time_range,
                    sources=sources,
                    limit=limit,
                )
            return []

        try:
            response = self._client.stores.search(
                query=query,
                store_identifiers=[self._ensure_store()],
                top_k=limit * self._overfetch,
                search_options={
                    "agentic": self._agentic,
                    "return_metadata": True,
                },
            )
        except Exception as exc:  # noqa: BLE001
            if self._fallback is not None:
                logger.warning(
                    "mixedbread search failed (%s); falling back to local "
                    "hybrid search",
                    exc,
                )
                return self._fallback.search(
                    query,
                    person=person,
                    time_range=time_range,
                    sources=sources,
                    limit=limit,
                )
            raise

        chunks = [c for c in response.data if getattr(c, "text", None)]
        ext_ids = [c.external_id for c in chunks if getattr(c, "external_id", None)]
        by_id = self._hydrate(
            ext_ids, person=person, time_range=time_range, sources=sources
        )
        filters_active = bool(person or time_range or sources)

        hits: List[SearchHit] = []
        for chunk in chunks:
            if len(hits) >= limit:
                break
            ext = getattr(chunk, "external_id", None)
            row = by_id.get(ext) if ext else None
            if row is not None:
                hits.append(self._hit_from_row(row, float(chunk.score)))
            elif ext is None and not filters_active:
                # A store file not mirrored from the knowledge base (e.g.
                # uploaded directly to the same store). Without a local row
                # we cannot verify structured filters, so only surface it
                # in unfiltered searches.
                hits.append(self._hit_from_remote(chunk))
        return hits

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_store(self) -> str:
        from openjarvis.tools.storage.mixedbread_backend import resolve_store_id

        if self._store_id is None:
            with self._store_lock:
                if self._store_id is None:
                    self._store_id = resolve_store_id(self._client, self._store_name)
        return self._store_id

    def _hydrate(
        self,
        chunk_ids: List[str],
        *,
        person: Optional[str],
        time_range: Optional[Tuple[Optional[datetime], Optional[datetime]]],
        sources: Optional[Sequence[str]],
    ) -> dict:
        """Fetch local rows for *chunk_ids* that pass the structured filters."""
        if not chunk_ids:
            return {}
        return self._store.get_live_chunks(
            chunk_ids,
            person=person,
            time_range=time_range,
            sources=sources,
        )

    def _hit_from_row(self, row: Any, score: float) -> SearchHit:
        thread_id = row["thread_id"] or ""
        return SearchHit(
            chunk_id=row["id"],
            document_id=row["doc_id"],
            chunk_idx=int(row["chunk_index"]),
            title=row["title"] or "",
            content_snippet=_snippet(row["content"]),
            source=row["source"] or "",
            timestamp=row["timestamp"] or "",
            participants=_parse_participants(row["participants"]),
            score=score,
            bm25_score=0.0,
            vector_score=0.0,
            thread_id=thread_id,
            thread_context=self._helper.thread_context(thread_id, row["id"]),
            url=row["url"] or "",
        )

    def close(self) -> None:
        """Close the SDK client when this instance created it."""
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "MixedbreadSearch":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @staticmethod
    def _hit_from_remote(chunk: Any) -> SearchHit:
        meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
        return SearchHit(
            chunk_id=chunk.file_id,
            document_id=chunk.file_id,
            chunk_idx=int(chunk.chunk_index),
            title=str(meta.get("title") or chunk.filename),
            content_snippet=_snippet(chunk.text or ""),
            source=str(meta.get("source") or "mixedbread"),
            timestamp=str(meta.get("timestamp") or ""),
            participants=[],
            score=float(chunk.score),
            bm25_score=0.0,
            vector_score=0.0,
        )


__all__ = [
    "DEFAULT_KNOWLEDGE_STORE",
    "MIRROR_METADATA_KEY",
    "MixedbreadKnowledgeSync",
    "MixedbreadSearch",
    "SyncReport",
]
