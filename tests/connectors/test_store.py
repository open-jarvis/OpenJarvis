"""Tests for KnowledgeStore — source-aware SQLite/FTS5 memory backend."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from openjarvis.connectors.store import KnowledgeStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(ks: KnowledgeStore, **kwargs) -> str:  # type: ignore[type-arg]
    """Convenience wrapper with sensible defaults."""
    defaults = {
        "content": "default content",
        "source": "test",
        "doc_type": "note",
        "doc_id": None,
        "title": "",
        "author": "",
        "participants": None,
        "timestamp": None,
        "thread_id": None,
        "url": None,
        "metadata": None,
        "chunk_index": 0,
    }
    defaults.update(kwargs)
    return ks.store(**defaults)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ks(tmp_path: Path) -> KnowledgeStore:
    db = tmp_path / "test_knowledge.db"
    return KnowledgeStore(db_path=db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_store_and_retrieve_basic(ks: KnowledgeStore) -> None:
    """Stored content can be retrieved by a matching query."""
    _store(
        ks,
        content="The quick brown fox jumps over the lazy dog",
        source="notes",
        doc_type="note",
    )
    results = ks.retrieve("quick brown fox", top_k=5)
    assert len(results) >= 1
    assert "fox" in results[0].content.lower() or "quick" in results[0].content.lower()
    assert results[0].score > 0.0


def test_retrieve_filter_by_source(ks: KnowledgeStore) -> None:
    """retrieve() with source= returns only chunks from that source."""
    _store(ks, content="Email about project alpha", source="gmail", doc_type="email")
    _store(
        ks,
        content="Note about project alpha progress",
        source="obsidian",
        doc_type="note",
    )

    gmail_results = ks.retrieve("project alpha", top_k=10, source="gmail")
    for r in gmail_results:
        assert r.metadata.get("source") == "gmail"

    obsidian_results = ks.retrieve("project alpha", top_k=10, source="obsidian")
    for r in obsidian_results:
        assert r.metadata.get("source") == "obsidian"

    assert len(gmail_results) >= 1
    assert len(obsidian_results) >= 1


def test_retrieve_filter_by_doc_type(ks: KnowledgeStore) -> None:
    """retrieve() with doc_type= filters correctly."""
    _store(
        ks,
        content="Meeting notes from Monday",
        source="calendar",
        doc_type="meeting",
    )
    _store(
        ks,
        content="Meeting email received Tuesday",
        source="gmail",
        doc_type="email",
    )

    meeting_results = ks.retrieve("meeting", top_k=10, doc_type="meeting")
    for r in meeting_results:
        assert r.metadata.get("doc_type") == "meeting"

    email_results = ks.retrieve("meeting", top_k=10, doc_type="email")
    for r in email_results:
        assert r.metadata.get("doc_type") == "email"

    assert len(meeting_results) >= 1
    assert len(email_results) >= 1


def test_retrieve_filter_by_author(ks: KnowledgeStore) -> None:
    """retrieve() with author= filters correctly."""
    _store(
        ks,
        content="Alice wrote about machine learning research",
        source="gmail",
        doc_type="email",
        author="alice@example.com",
    )
    _store(
        ks,
        content="Bob wrote about machine learning deployment",
        source="gmail",
        doc_type="email",
        author="bob@example.com",
    )

    alice_results = ks.retrieve(
        "machine learning", top_k=10, author="alice@example.com"
    )
    for r in alice_results:
        assert r.metadata.get("author") == "alice@example.com"

    bob_results = ks.retrieve("machine learning", top_k=10, author="bob@example.com")
    for r in bob_results:
        assert r.metadata.get("author") == "bob@example.com"

    assert len(alice_results) >= 1
    assert len(bob_results) >= 1


def test_retrieve_filter_by_timestamp_since(ks: KnowledgeStore) -> None:
    """retrieve() with since= excludes older documents."""
    old_ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
    new_ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
    cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)

    _store(ks, content="Old document about research", source="notes", timestamp=old_ts)
    _store(ks, content="New document about research", source="notes", timestamp=new_ts)

    results = ks.retrieve("document research", top_k=10, since=cutoff)
    for r in results:
        ts_str = r.metadata.get("timestamp", "")
        assert ts_str >= cutoff.isoformat(), f"Got old doc in results: {ts_str}"

    assert len(results) >= 1


def test_delete_by_doc_id(ks: KnowledgeStore) -> None:
    """delete() removes all chunks with matching doc_id."""
    doc_id = "test:doc:001"
    _store(
        ks,
        content="First chunk of the document",
        source="notes",
        doc_id=doc_id,
        chunk_index=0,
    )
    _store(
        ks,
        content="Second chunk of the document",
        source="notes",
        doc_id=doc_id,
        chunk_index=1,
    )
    _store(
        ks,
        content="Other document content",
        source="notes",
        doc_id="other:doc:001",
        chunk_index=0,
    )

    # Confirm items are stored
    before = ks.retrieve("document", top_k=10)
    assert len(before) >= 3

    deleted = ks.delete(doc_id)
    assert deleted is True

    # Only the other doc should remain
    after = ks.retrieve("document", top_k=10)
    for r in after:
        assert r.metadata.get("doc_id") != doc_id

    # Deleting non-existent doc_id returns False
    assert ks.delete("nonexistent:doc") is False


def test_clear(ks: KnowledgeStore) -> None:
    """clear() removes all stored documents."""
    _store(ks, content="Document one about research")
    _store(ks, content="Document two about analysis")
    _store(ks, content="Document three about synthesis")

    before = ks.retrieve("document", top_k=10)
    assert len(before) >= 3

    ks.clear()

    after = ks.retrieve("document", top_k=10)
    assert len(after) == 0


def test_store_with_metadata(ks: KnowledgeStore) -> None:
    """Extra metadata and thread_id are preserved in retrieval results."""
    custom_meta = {"labels": ["important", "action-needed"], "priority": "high"}
    chunk_id = _store(
        ks,
        content="Meeting follow-up with action items",
        source="gmail",
        doc_type="email",
        thread_id="thread:abc:123",
        metadata=custom_meta,
    )
    assert chunk_id  # non-empty string

    results = ks.retrieve("action items", top_k=5)
    assert len(results) >= 1
    meta = results[0].metadata
    assert meta.get("thread_id") == "thread:abc:123"
    # Custom metadata should also be available
    assert "labels" in meta or meta.get("metadata", {}).get("labels") is not None


def test_store_preserves_url(ks: KnowledgeStore) -> None:
    """URL field survives the store/retrieve round-trip."""
    url = "https://mail.google.com/mail/u/0/#inbox/abc123"
    _store(
        ks,
        content="Email with a specific URL for testing",
        source="gmail",
        doc_type="email",
        url=url,
    )
    results = ks.retrieve("specific URL testing", top_k=5)
    assert len(results) >= 1
    assert results[0].metadata.get("url") == url


def test_retrieve_empty_store(ks: KnowledgeStore) -> None:
    """Querying an empty store returns an empty list (no crash)."""
    results = ks.retrieve("anything", top_k=5)
    assert results == []


def test_retrieve_top_k_respected(ks: KnowledgeStore) -> None:
    """top_k limits the number of returned results."""
    for i in range(10):
        _store(
            ks,
            content=f"Research document number {i} about topic X",
            source="notes",
        )

    results = ks.retrieve("research topic", top_k=3)
    assert len(results) <= 3


def test_store_returns_unique_chunk_ids(ks: KnowledgeStore) -> None:
    """Each store() call returns a unique chunk id."""
    id1 = _store(ks, content="First chunk")
    id2 = _store(ks, content="Second chunk")
    assert id1 != id2


def test_retrieve_filter_by_until(ks: KnowledgeStore) -> None:
    """retrieve() with until= excludes newer documents."""
    old_ts = datetime(2023, 6, 1, tzinfo=timezone.utc)
    new_ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
    cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)

    _store(
        ks,
        content="Old quarterly report analysis",
        source="notes",
        timestamp=old_ts,
    )
    _store(
        ks,
        content="New quarterly report analysis",
        source="notes",
        timestamp=new_ts,
    )

    results = ks.retrieve("quarterly report", top_k=10, until=cutoff)
    for r in results:
        ts_str = r.metadata.get("timestamp", "")
        assert ts_str <= cutoff.isoformat(), f"Got new doc in results: {ts_str}"

    assert len(results) >= 1


def test_memory_store_event_emitted(tmp_path: Path) -> None:
    """MEMORY_STORE event is published on store()."""
    from openjarvis.core.events import EventType, get_event_bus, reset_event_bus

    reset_event_bus()
    bus = get_event_bus(record_history=True)
    ks = KnowledgeStore(db_path=tmp_path / "events.db")

    _store(ks, content="Event emission test content", source="test")

    types = [e.event_type for e in bus.history]
    assert EventType.MEMORY_STORE in types


def test_memory_retrieve_event_emitted(tmp_path: Path) -> None:
    """MEMORY_RETRIEVE event is published on retrieve()."""
    from openjarvis.core.events import EventType, get_event_bus, reset_event_bus

    reset_event_bus()
    bus = get_event_bus(record_history=True)
    ks = KnowledgeStore(db_path=tmp_path / "events2.db")

    _store(ks, content="Some content to retrieve", source="test")
    ks.retrieve("some content", top_k=5)

    types = [e.event_type for e in bus.history]
    assert EventType.MEMORY_RETRIEVE in types
