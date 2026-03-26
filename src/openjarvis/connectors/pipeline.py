"""IngestionPipeline — deduplicate, chunk, and store Documents.

Takes ``Document`` objects from connectors, deduplicates by ``doc_id``,
splits content using ``SemanticChunker``, and persists chunks to a
``KnowledgeStore``.

Typical usage::

    store = KnowledgeStore(db_path=":memory:")
    pipeline = IngestionPipeline(store)
    n_chunks = pipeline.ingest(connector.sync())
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from openjarvis.connectors._stubs import Attachment, Document
from openjarvis.connectors.chunker import SemanticChunker
from openjarvis.connectors.store import KnowledgeStore

if TYPE_CHECKING:
    from openjarvis.connectors.attachment_store import AttachmentStore


class IngestionPipeline:
    """Deduplicate, chunk, and index documents into a KnowledgeStore.

    Parameters
    ----------
    store:
        The ``KnowledgeStore`` instance to write chunks into.
    max_tokens:
        Soft upper-limit on chunk size passed to ``SemanticChunker``.
    attachment_store:
        Optional ``AttachmentStore`` for persisting attachment blobs and
        extracting text from supported MIME types (PDF, plain text, etc.).
        When ``None`` (default) attachments are silently ignored.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        max_tokens: int = 512,
        attachment_store: Optional[AttachmentStore] = None,
    ) -> None:
        self._store = store
        self._chunker = SemanticChunker(max_tokens=max_tokens)
        self._attachment_store = attachment_store
        self._seen_doc_ids: set[str] = set()
        self._load_existing_doc_ids()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_existing_doc_ids(self) -> None:
        """Populate ``_seen_doc_ids`` from rows already in the store."""
        rows = self._store._conn.execute(
            "SELECT DISTINCT doc_id FROM knowledge_chunks"
        ).fetchall()
        self._seen_doc_ids = {r[0] for r in rows}

    def _extract_attachment_text(self, att: Attachment) -> str:
        """Extract text from an attachment.

        Returns the extracted text, or an empty string if the MIME type is
        unsupported or extraction fails.
        """
        if att.mime_type == "application/pdf":
            try:
                import io

                import pdfplumber

                with pdfplumber.open(io.BytesIO(att.content)) as pdf:
                    return "\n".join(page.extract_text() or "" for page in pdf.pages)
            except Exception:  # noqa: BLE001
                return ""
        if att.mime_type in ("text/plain", "text/markdown", "text/csv"):
            return att.content.decode("utf-8", errors="replace")
        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, documents: Iterable[Document]) -> int:
        """Ingest an iterable of documents into the knowledge store.

        Duplicate ``doc_id`` values are silently skipped (both across
        calls and within a single batch).

        Parameters
        ----------
        documents:
            An iterable of ``Document`` objects (e.g. from a connector's
            ``sync()`` method).

        Returns
        -------
        int
            The total number of chunks written to the store in this call.
        """
        chunks_stored = 0

        for doc in documents:
            if doc.doc_id in self._seen_doc_ids:
                continue

            # Build the parent metadata dict that will be inherited by every
            # chunk produced from this document.
            parent_meta = {
                "title": doc.title,
                "author": doc.author,
                "source": doc.source,
                "doc_type": doc.doc_type,
                "url": doc.url or "",
                "thread_id": doc.thread_id or "",
            }
            # Merge any extra connector-level metadata (without overwriting
            # the standard provenance fields set above).
            parent_meta.update(doc.metadata)

            # Normalise the timestamp to a string once.
            if hasattr(doc.timestamp, "isoformat"):
                timestamp_str = doc.timestamp.isoformat()
            else:
                timestamp_str = str(doc.timestamp)

            # Chunk the document content using the type-aware strategy.
            chunks = self._chunker.chunk(
                doc.content,
                doc_type=doc.doc_type,
                metadata=parent_meta,
            )

            for chunk in chunks:
                self._store.store(
                    content=chunk.content,
                    source=doc.source,
                    doc_type=doc.doc_type,
                    doc_id=doc.doc_id,
                    title=doc.title,
                    author=doc.author,
                    participants=doc.participants,
                    timestamp=timestamp_str,
                    thread_id=doc.thread_id,
                    url=doc.url,
                    metadata=chunk.metadata,
                    chunk_index=chunk.index,
                )
                chunks_stored += 1

            # Process attachments when an attachment store is configured.
            if self._attachment_store and doc.attachments:
                for att in doc.attachments:
                    if not att.content:
                        continue

                    # Persist the raw blob and obtain its SHA-256.
                    sha = self._attachment_store.store(
                        content=att.content,
                        filename=att.filename,
                        mime_type=att.mime_type,
                        source_doc_id=doc.doc_id,
                    )

                    # Extract searchable text and index it as additional chunks.
                    extracted = self._extract_attachment_text(att)
                    if extracted:
                        att_chunks = self._chunker.chunk(
                            extracted,
                            doc_type=doc.doc_type,
                            metadata={
                                **parent_meta,
                                "attachment": att.filename,
                                "sha256": sha,
                            },
                        )
                        for chunk in att_chunks:
                            self._store.store(
                                content=chunk.content,
                                source=doc.source,
                                doc_type=doc.doc_type,
                                doc_id=doc.doc_id,
                                title=f"{doc.title} [{att.filename}]",
                                author=doc.author,
                                participants=doc.participants,
                                timestamp=timestamp_str,
                                thread_id=doc.thread_id,
                                url=doc.url,
                                metadata=chunk.metadata,
                                chunk_index=chunk.index,
                            )
                            chunks_stored += 1

            self._seen_doc_ids.add(doc.doc_id)

        return chunks_stored


__all__ = ["IngestionPipeline"]
