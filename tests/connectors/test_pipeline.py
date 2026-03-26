"""Tests for IngestionPipeline — dedup, chunking, and indexed storage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(**kwargs) -> Document:  # type: ignore[type-arg]
    """Build a Document with sensible defaults."""
    defaults = dict(
        doc_id="doc:001",
        source="test",
        doc_type="note",
        content="Hello world this is a test document.",
        title="Test Doc",
        author="tester@example.com",
        participants=[],
        timestamp=datetime(2025, 1, 15, tzinfo=timezone.utc),
        thread_id=None,
        url=None,
        metadata={},
    )
    defaults.update(kwargs)
    return Document(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(db_path=tmp_path / "test_pipeline.db")


@pytest.fixture()
def pipeline(store: KnowledgeStore) -> IngestionPipeline:
    return IngestionPipeline(store)


# ---------------------------------------------------------------------------
# Test 1: ingest single short document → 1 chunk stored, retrievable
# ---------------------------------------------------------------------------


def test_ingest_single_short_document(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """A short document produces exactly one chunk that is retrievable."""
    doc = _make_doc(
        doc_id="doc:short:001",
        content="The quick brown fox jumps over the lazy dog.",
        source="obsidian",
        doc_type="note",
        title="Fox Note",
    )

    n = pipeline.ingest([doc])

    assert n == 1
    assert store.count() == 1

    results = store.retrieve("quick brown fox", top_k=5)
    assert len(results) >= 1
    assert results[0].metadata.get("source") == "obsidian"
    assert results[0].metadata.get("doc_id") == "doc:short:001"
    assert results[0].metadata.get("title") == "Fox Note"


# ---------------------------------------------------------------------------
# Test 2: ingest same doc_id twice → only 1 copy stored (dedup)
# ---------------------------------------------------------------------------


def test_ingest_dedup_same_doc_id(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """Ingesting the same doc_id a second time produces no new chunks."""
    doc = _make_doc(
        doc_id="doc:dedup:001",
        content="Deduplication should prevent double-storing this content.",
    )

    first = pipeline.ingest([doc])
    second = pipeline.ingest([doc])

    assert first == 1
    assert second == 0  # no new chunks added
    assert store.count() == 1


def test_ingest_dedup_within_batch(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """Duplicate doc_ids within the same batch are deduplicated."""
    doc_a = _make_doc(doc_id="doc:batch:dup", content="First occurrence of this doc.")
    doc_b = _make_doc(doc_id="doc:batch:dup", content="Second occurrence of this doc.")

    n = pipeline.ingest([doc_a, doc_b])

    # Only the first occurrence should be stored
    assert n == 1
    assert store.count() == 1


def test_ingest_dedup_persists_across_pipeline_instances(
    store: KnowledgeStore,
) -> None:
    """A new IngestionPipeline instance loads existing doc_ids from the store."""
    doc = _make_doc(
        doc_id="doc:persist:001",
        content="This document should be present before the second pipeline.",
    )

    pipeline1 = IngestionPipeline(store)
    pipeline1.ingest([doc])
    assert store.count() == 1

    # New pipeline instance should load existing doc_ids from the store
    pipeline2 = IngestionPipeline(store)
    n = pipeline2.ingest([doc])

    assert n == 0
    assert store.count() == 1  # still only 1 chunk


# ---------------------------------------------------------------------------
# Test 3: ingest long document → multiple chunks, all inherit parent metadata
# ---------------------------------------------------------------------------


def test_ingest_long_document_multiple_chunks(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """A document exceeding max_tokens is split into multiple chunks."""
    # Create a pipeline with a very small max_tokens to force splitting
    small_store = KnowledgeStore(db_path=":memory:")
    small_pipeline = IngestionPipeline(small_store, max_tokens=10)

    # Build a document with many sentences that will exceed 10 tokens each
    sentences = [
        f"This is sentence number {i} about machine learning research topics."
        for i in range(20)
    ]
    long_content = " ".join(sentences)

    doc = _make_doc(
        doc_id="doc:long:001",
        source="gmail",
        doc_type="email",
        content=long_content,
        title="Long Email",
        author="sender@example.com",
    )

    n = small_pipeline.ingest([doc])

    assert n > 1, f"Expected multiple chunks, got {n}"
    assert small_store.count() == n

    # All chunks must inherit parent metadata
    rows = small_store._conn.execute(
        "SELECT source, doc_type, title, author, doc_id FROM knowledge_chunks"
    ).fetchall()
    for row in rows:
        assert row[0] == "gmail"
        assert row[1] == "email"
        assert row[2] == "Long Email"
        assert row[3] == "sender@example.com"
        assert row[4] == "doc:long:001"


# ---------------------------------------------------------------------------
# Test 4: ingest event → single chunk (atomic, never split)
# ---------------------------------------------------------------------------


def test_ingest_event_single_chunk(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """Event documents always produce exactly one chunk regardless of length."""
    event_content = (
        "Team all-hands meeting on Thursday at 2pm in the main conference room. "
        "Agenda: Q1 review, roadmap discussion, team announcements, open Q&A session. "
        "Please bring your laptops and any relevant documents for review."
    )
    doc = _make_doc(
        doc_id="event:001",
        source="google_calendar",
        doc_type="event",
        content=event_content,
        title="All-Hands Q1",
    )

    n = pipeline.ingest([doc])

    # Events are atomic — must be exactly 1 chunk
    assert n == 1
    assert store.count() == 1

    results = store.retrieve("team meeting conference room", top_k=5)
    assert len(results) >= 1
    assert results[0].metadata.get("source") == "google_calendar"
    assert results[0].metadata.get("doc_type") == "event"


# ---------------------------------------------------------------------------
# Test 5: ingest from multiple sources → filter by source works
# ---------------------------------------------------------------------------


def test_ingest_multiple_sources_filter(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """Chunks from different sources can be filtered independently."""
    gmail_doc = _make_doc(
        doc_id="gmail:thread:abc",
        source="gmail",
        doc_type="email",
        content="Email discussing the quarterly research budget allocation.",
        title="Q1 Budget Email",
        author="alice@example.com",
    )
    obsidian_doc = _make_doc(
        doc_id="obsidian:note:xyz",
        source="obsidian",
        doc_type="note",
        content="Research notes on quarterly budget planning strategies.",
        title="Budget Note",
        author="bob@example.com",
    )
    slack_doc = _make_doc(
        doc_id="slack:msg:001",
        source="slack",
        doc_type="message",
        content="Slack message about quarterly budget review meeting.",
        title="",
        author="carol@example.com",
    )

    n = pipeline.ingest([gmail_doc, obsidian_doc, slack_doc])
    assert n == 3  # one chunk per short document

    # Filter by each source
    gmail_results = store.retrieve("quarterly budget", top_k=10, source="gmail")
    obsidian_results = store.retrieve("quarterly budget", top_k=10, source="obsidian")
    slack_results = store.retrieve("quarterly budget", top_k=10, source="slack")

    assert len(gmail_results) >= 1
    assert len(obsidian_results) >= 1
    assert len(slack_results) >= 1

    for r in gmail_results:
        assert r.metadata.get("source") == "gmail"
    for r in obsidian_results:
        assert r.metadata.get("source") == "obsidian"
    for r in slack_results:
        assert r.metadata.get("source") == "slack"


# ---------------------------------------------------------------------------
# Test 6: ingest returns correct chunk count across batches
# ---------------------------------------------------------------------------


def test_ingest_chunk_count_return_value(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """ingest() return value accurately reflects new chunks stored."""
    doc_a = _make_doc(doc_id="doc:count:001", content="First document content here.")
    doc_b = _make_doc(doc_id="doc:count:002", content="Second document content here.")
    doc_c = _make_doc(doc_id="doc:count:003", content="Third document content here.")

    # First batch: 2 new docs
    n1 = pipeline.ingest([doc_a, doc_b])
    assert n1 == 2

    # Second batch: 1 new doc + 1 duplicate (doc_a)
    n2 = pipeline.ingest([doc_a, doc_c])
    assert n2 == 1  # only doc_c is new

    assert store.count() == 3
