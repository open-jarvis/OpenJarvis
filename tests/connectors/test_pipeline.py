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


# ---------------------------------------------------------------------------
# v1 schema tests — pipeline-side derivation
# ---------------------------------------------------------------------------


def test_thread_id_namespaced_at_pipeline(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """Pipeline prefixes raw thread_id with '{source}:' so connectors can't forget."""
    doc = _make_doc(
        doc_id="gmail:msg-tn1",
        source="gmail",
        thread_id="raw-thread-id",
        content="Thread namespacing should happen here.",
    )
    pipeline.ingest([doc])

    rows = store._conn.execute(
        "SELECT thread_id FROM knowledge_chunks"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "gmail:raw-thread-id"


def test_thread_id_namespacing_is_idempotent(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """A connector that already namespaced thread_id is not double-prefixed."""
    doc = _make_doc(
        doc_id="gmail:msg-tn2",
        source="gmail",
        thread_id="gmail:already-prefixed",
        content="Idempotent namespacing keeps a single prefix.",
    )
    pipeline.ingest([doc])

    rows = store._conn.execute(
        "SELECT thread_id FROM knowledge_chunks"
    ).fetchall()
    assert rows[0][0] == "gmail:already-prefixed"


def test_source_id_derived_from_doc_id_prefix(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """When source_id isn't set on the Document, the pipeline strips '{source}:'
    from doc_id so legacy connectors keep working."""
    doc = _make_doc(
        doc_id="gmail:msg42",
        source="gmail",
        content="Legacy connector with composite doc_id.",
    )
    pipeline.ingest([doc])

    rows = store._conn.execute(
        "SELECT source_id FROM knowledge_chunks"
    ).fetchall()
    assert rows[0][0] == "msg42"


def test_source_id_uses_explicit_field_when_set(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """An explicit Document.source_id wins over any prefix-stripping heuristic."""
    doc = _make_doc(
        doc_id="some-other-shape",
        source="gmail",
        content="Explicit source_id should be used verbatim.",
    )
    doc.source_id = "explicit-src-id"
    pipeline.ingest([doc])

    rows = store._conn.execute(
        "SELECT source_id FROM knowledge_chunks"
    ).fetchall()
    assert rows[0][0] == "explicit-src-id"


def test_content_hash_computed_per_chunk(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """content_hash equals sha256(chunk.content) for a single-chunk document."""
    import hashlib as _hashlib

    content = "Hello world this is a test document."
    doc = _make_doc(doc_id="doc:hash:1", content=content)
    pipeline.ingest([doc])

    rows = store._conn.execute(
        "SELECT content, content_hash FROM knowledge_chunks"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == _hashlib.sha256(rows[0][0].encode("utf-8")).hexdigest()


def test_last_synced_set_at_ingest(
    pipeline: IngestionPipeline, store: KnowledgeStore
) -> None:
    """last_synced is populated with the ingest time, not 0 default."""
    import time as _time

    before = _time.time()
    pipeline.ingest([_make_doc(doc_id="doc:ls:1", content="Last synced check.")])
    after = _time.time()

    rows = store._conn.execute(
        "SELECT last_synced FROM knowledge_chunks"
    ).fetchall()
    assert len(rows) == 1
    assert before <= rows[0][0] <= after


# ---------------------------------------------------------------------------
# Embedding wire-up
# ---------------------------------------------------------------------------


class _StubEmbedder:
    """Deterministic in-test embedder that mimics the OllamaEmbedder surface."""

    model_version = "stub:test-embedder"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str):  # type: ignore[no-untyped-def]
        import numpy as _np
        self.calls += 1
        # Map content to a stable 4-d float32 vector for assertion convenience.
        h = abs(hash(text)) % 10_000
        return _np.asarray([h, h + 1, h + 2, h + 3], dtype=_np.float32).tobytes()


def test_pipeline_populates_embedding_when_embedder_provided(
    store: KnowledgeStore,
) -> None:
    """Pipeline writes float32 embedding bytes + model_version when embedder is set."""
    import numpy as _np

    embedder = _StubEmbedder()
    pipeline = IngestionPipeline(store, embedder=embedder)
    pipeline.ingest([_make_doc(doc_id="doc:emb:1", content="Short embeddable text.")])

    rows = store._conn.execute(
        "SELECT embedding, embedding_model_version FROM knowledge_chunks"
    ).fetchall()
    assert len(rows) == 1
    blob, version = rows[0]
    assert blob is not None
    arr = _np.frombuffer(blob, dtype=_np.float32)
    assert arr.shape == (4,)
    assert version == "stub:test-embedder"
    assert embedder.calls == 1


def test_pipeline_skips_embedding_when_no_embedder(
    pipeline: IngestionPipeline, store: KnowledgeStore,
) -> None:
    """Default pipeline leaves embedding NULL and embedding_model_version empty."""
    pipeline.ingest(
        [_make_doc(doc_id="doc:emb:none", content="No embedder configured.")]
    )

    rows = store._conn.execute(
        "SELECT embedding, embedding_model_version FROM knowledge_chunks"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] is None
    assert rows[0][1] == ""
