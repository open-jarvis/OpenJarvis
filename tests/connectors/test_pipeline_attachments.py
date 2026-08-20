"""Tests for attachment processing in IngestionPipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from openjarvis.connectors._stubs import Attachment, Document
from openjarvis.connectors.attachment_store import AttachmentStore
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(**kwargs) -> Document:  # type: ignore[type-arg]
    """Build a Document with sensible defaults."""
    defaults = dict(
        doc_id="doc:att:001",
        source="gmail",
        doc_type="email",
        content="Main body of the email.",
        title="Test Email",
        author="sender@example.com",
        participants=[],
        timestamp=datetime(2025, 3, 1, tzinfo=timezone.utc),
        thread_id=None,
        url=None,
        attachments=[],
        metadata={},
    )
    defaults.update(kwargs)
    return Document(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(db_path=tmp_path / "att_pipeline.db")


@pytest.fixture()
def att_store(tmp_path: Path) -> AttachmentStore:
    return AttachmentStore(base_dir=str(tmp_path / "blobs"))


@pytest.fixture()
def pipeline(store: KnowledgeStore, att_store: AttachmentStore) -> IngestionPipeline:
    return IngestionPipeline(store, attachment_store=att_store)


# ---------------------------------------------------------------------------
# Test 1: text/plain attachment text is indexed and searchable
# ---------------------------------------------------------------------------


def test_plain_text_attachment_indexed(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """Ingesting a doc with a text/plain attachment indexes the attachment text."""
    att_text = b"Deep learning quarterly report: model accuracy improved by 15%."
    att = Attachment(
        filename="report.txt",
        mime_type="text/plain",
        size_bytes=len(att_text),
        content=att_text,
    )
    doc = _make_doc(
        doc_id="doc:att:plain:001",
        content="Please see the attached report.",
        title="Q1 Report Email",
        attachments=[att],
    )

    n = pipeline.ingest([doc])

    # Expect at least 2 chunks: 1 from the main body + 1 from the attachment
    assert n >= 2

    # Attachment text must be retrievable
    results = store.retrieve("model accuracy improved", top_k=5)
    assert len(results) >= 1

    # At least one result should come from the attachment chunk
    att_results = [r for r in results if r.metadata.get("attachment") == "report.txt"]
    assert len(att_results) >= 1

    # Title for attachment chunks includes the filename in brackets
    assert "report.txt" in att_results[0].metadata.get("title", "")


# ---------------------------------------------------------------------------
# Test 2: blob is stored in AttachmentStore
# ---------------------------------------------------------------------------


def test_attachment_blob_stored(
    pipeline: IngestionPipeline, att_store: AttachmentStore
) -> None:
    """The raw bytes of an attachment are persisted in the AttachmentStore."""
    att_content = b"Confidential: merger details enclosed."
    att = Attachment(
        filename="merger.txt",
        mime_type="text/plain",
        size_bytes=len(att_content),
        content=att_content,
    )
    doc = _make_doc(
        doc_id="doc:att:blob:001",
        content="See attached for details.",
        attachments=[att],
    )

    pipeline.ingest([doc])

    # The blob must be retrievable from the attachment store
    import hashlib

    expected_sha = hashlib.sha256(att_content).hexdigest()
    stored_bytes = att_store.get_content(expected_sha)
    assert stored_bytes == att_content

    # Metadata must link back to the source document
    meta = att_store.get_metadata(expected_sha)
    assert meta is not None
    assert meta["filename"] == "merger.txt"
    assert meta["mime_type"] == "text/plain"
    assert "doc:att:blob:001" in meta["source_doc_ids"]


# ---------------------------------------------------------------------------
# Test 3: no regression when doc has no attachments
# ---------------------------------------------------------------------------


def test_no_attachments_no_regression(
    store: KnowledgeStore, att_store: AttachmentStore
) -> None:
    """Pipeline with attachment_store handles docs without attachments correctly."""
    pipeline = IngestionPipeline(store, attachment_store=att_store)

    doc = _make_doc(
        doc_id="doc:no:att:001",
        content="Just a regular email with no attachments.",
        attachments=[],
    )

    n = pipeline.ingest([doc])

    assert n == 1
    assert store.count() == 1

    # No blobs should be stored
    rows = att_store._conn.execute("SELECT COUNT(*) FROM attachments").fetchone()
    assert rows[0] == 0
