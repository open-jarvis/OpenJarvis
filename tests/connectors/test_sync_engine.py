"""Tests for SyncEngine — checkpoint/resume connector orchestration."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

import pytest

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.connectors.sync_engine import SyncEngine

# ---------------------------------------------------------------------------
# StubConnector test helper
# ---------------------------------------------------------------------------


class StubConnector(BaseConnector):
    """Minimal connector that replays a pre-built list of documents."""

    connector_id = "stub"
    display_name = "Stub"
    auth_type = "filesystem"

    def __init__(self, docs: List[Document]) -> None:
        self._docs = docs

    # BaseConnector abstract methods

    def is_connected(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        yield from self._docs

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=len(self._docs))


class RecordingConnector(BaseConnector):
    """Replays documents, recording `since` on each call, optionally
    raising partway through to simulate a sync that dies mid-stream."""

    connector_id = "recorder"
    display_name = "Recorder"
    auth_type = "filesystem"

    def __init__(
        self,
        docs: List[Document],
        *,
        fail_after: Optional[int] = None,
    ) -> None:
        self._docs = docs
        self._fail_after = fail_after
        self.received_since: List[Optional[datetime]] = []

    def is_connected(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        self.received_since.append(since)
        for i, doc in enumerate(self._docs):
            if self._fail_after is not None and i == self._fail_after:
                raise RuntimeError("connector exploded mid-sync")
            yield doc

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=len(self._docs))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    doc_id: str, source: str = "stub", content: str = "Test content."
) -> Document:
    return Document(
        doc_id=doc_id,
        source=source,
        doc_type="note",
        content=content,
        title=f"Doc {doc_id}",
        author="tester@example.com",
        timestamp=datetime(2025, 3, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(db_path=tmp_path / "knowledge.db")


@pytest.fixture()
def pipeline(store: KnowledgeStore) -> IngestionPipeline:
    return IngestionPipeline(store)


@pytest.fixture()
def engine(pipeline: IngestionPipeline, tmp_path: Path) -> SyncEngine:
    return SyncEngine(pipeline, state_db=str(tmp_path / "sync_state.db"))


# ---------------------------------------------------------------------------
# Test 1: sync_connector — 5 docs from StubConnector all stored
# ---------------------------------------------------------------------------


def test_sync_connector(engine: SyncEngine, store: KnowledgeStore) -> None:
    """StubConnector yields 5 docs; all are ingested and retrievable."""
    docs = [
        _make_doc(f"doc:{i}", content=f"Unique content for document {i}")
        for i in range(5)
    ]
    connector = StubConnector(docs)

    items = engine.sync(connector)

    assert items == 5
    # Each short doc produces exactly one chunk
    assert store.count() == 5


# ---------------------------------------------------------------------------
# Test 2: sync_saves_checkpoint — checkpoint items_synced is correct
# ---------------------------------------------------------------------------


def test_sync_saves_checkpoint(engine: SyncEngine) -> None:
    """After a sync, get_checkpoint returns the correct items_synced count."""
    docs = [_make_doc(f"cp:doc:{i}") for i in range(3)]
    connector = StubConnector(docs)

    engine.sync(connector)

    cp = engine.get_checkpoint("stub")
    assert cp is not None
    assert cp["items_synced"] == 3
    assert cp["last_sync"] is not None
    assert cp["error"] is None


# ---------------------------------------------------------------------------
# Test 3: sync_status_for_unsynced — None for unknown connector
# ---------------------------------------------------------------------------


def test_sync_status_for_unsynced(engine: SyncEngine) -> None:
    """get_checkpoint returns None for a connector that has never been synced."""
    result = engine.get_checkpoint("never_synced_connector")
    assert result is None


# ---------------------------------------------------------------------------
# Test 4: sync_multiple_connectors — filter by source works
# ---------------------------------------------------------------------------


def test_sync_multiple_connectors(
    pipeline: IngestionPipeline, store: KnowledgeStore, tmp_path: Path
) -> None:
    """Two connectors with different sources can be filtered independently."""

    class StubConnectorA(StubConnector):
        connector_id = "stub_a"

    class StubConnectorB(StubConnector):
        connector_id = "stub_b"

    docs_a = [
        _make_doc(f"a:doc:{i}", source="source_a", content=f"Alpha content {i}")
        for i in range(3)
    ]
    docs_b = [
        _make_doc(f"b:doc:{i}", source="source_b", content=f"Beta content {i}")
        for i in range(4)
    ]

    engine = SyncEngine(pipeline, state_db=str(tmp_path / "multi_sync_state.db"))

    items_a = engine.sync(StubConnectorA(docs_a))
    items_b = engine.sync(StubConnectorB(docs_b))

    assert items_a == 3
    assert items_b == 4
    assert store.count() == 7

    # Filter by source: only source_a results
    results_a = store.retrieve("Alpha content", top_k=10, source="source_a")
    assert len(results_a) >= 1
    for r in results_a:
        assert r.metadata.get("source") == "source_a"

    # Filter by source: only source_b results
    results_b = store.retrieve("Beta content", top_k=10, source="source_b")
    assert len(results_b) >= 1
    for r in results_b:
        assert r.metadata.get("source") == "source_b"


# ---------------------------------------------------------------------------
# reset_checkpoint clears stale state after a data-source swap
# ---------------------------------------------------------------------------


def test_reset_checkpoint_clears_state(engine: SyncEngine) -> None:
    """A connector reconfigured to point at an entirely different data
    source (e.g. a user swaps which Obsidian vault is connected) must not
    resume from the old source's checkpoint. reset_checkpoint() clears the
    saved cursor/items_synced/last_sync for a connector_id so the next
    sync starts fresh."""
    docs = [_make_doc(f"reset:doc:{i}") for i in range(5)]
    connector = StubConnector(docs)

    engine.sync(connector)
    assert engine.get_checkpoint("stub") is not None

    engine.reset_checkpoint("stub")

    assert engine.get_checkpoint("stub") is None


def test_sync_after_reset_does_not_inherit_prior_items_or_since(
    engine: SyncEngine,
) -> None:
    """After reset_checkpoint, a new sync must start item counting from
    zero and pass since=None -- not the old source's watermark, which
    could cause new items from a freshly-connected source to be silently
    skipped if their timestamps predate it."""

    class TrackingConnector(StubConnector):
        connector_id = "swap"

        def __init__(self, docs: List[Document]) -> None:
            super().__init__(docs)
            self.received_since: List[Optional[datetime]] = []

        def sync(
            self,
            *,
            since: Optional[datetime] = None,
            cursor: Optional[str] = None,
        ) -> Iterator[Document]:
            self.received_since.append(since)
            yield from self._docs

    old_docs = [_make_doc(f"old:doc:{i}") for i in range(9)]
    engine.sync(TrackingConnector(old_docs))

    engine.reset_checkpoint("swap")

    new_docs = [_make_doc(f"new:doc:{i}") for i in range(1)]
    fresh = TrackingConnector(new_docs)
    items = engine.sync(fresh)

    assert fresh.received_since == [None]
    assert items == 1

    cp = engine.get_checkpoint("swap")
    assert cp is not None
    assert cp["items_synced"] == 1


def test_sync_honors_cancellation_before_ingestion(
    engine: SyncEngine,
    store: KnowledgeStore,
) -> None:
    cancel_event = threading.Event()
    cancel_event.set()

    items = engine.sync(
        StubConnector([_make_doc("cancelled:doc")]),
        cancel_event=cancel_event,
    )

    assert items == 0
    assert store.count() == 0


def test_sync_engine_context_manager_closes_sqlite(pipeline: IngestionPipeline) -> None:
    with SyncEngine(pipeline, state_db=":memory:") as scoped_engine:
        scoped_engine.get_checkpoint("stub")

    with pytest.raises(sqlite3.ProgrammingError):
        scoped_engine.get_checkpoint("stub")


# ---------------------------------------------------------------------------
# A failed or cancelled sync must not advance last_sync (#782)
# ---------------------------------------------------------------------------


def test_failed_sync_does_not_advance_last_sync(engine: SyncEngine) -> None:
    """A sync that dies partway through must preserve the prior watermark
    (None here, since this is the connector's first-ever sync) instead of
    recording the failure time as last_sync -- otherwise a retry would
    start from the failure time and permanently skip whatever the failed
    attempt never reached."""
    docs = [_make_doc(f"fail:doc:{i}") for i in range(5)]
    connector = RecordingConnector(docs, fail_after=3)

    with pytest.raises(RuntimeError, match="connector exploded mid-sync"):
        engine.sync(connector)

    cp = engine.get_checkpoint("recorder")
    assert cp is not None
    assert cp["last_sync"] is None
    assert cp["error"] is not None


def test_retry_after_failure_does_not_skip_the_failed_window(
    engine: SyncEngine,
) -> None:
    """End-to-end: after a failed sync, a retry must see the SAME `since`
    as the original attempt (None, since nothing ever succeeded) -- not a
    timestamp advanced by the failed attempt, which would silently skip
    the entire window the failure never got to process."""
    docs = [_make_doc(f"retry:doc:{i}") for i in range(5)]

    failing = RecordingConnector(docs, fail_after=3)
    with pytest.raises(RuntimeError):
        engine.sync(failing)
    assert failing.received_since == [None]

    retry = RecordingConnector(docs, fail_after=None)
    items = engine.sync(retry)

    assert retry.received_since == [None]
    assert items == 5

    cp = engine.get_checkpoint("recorder")
    assert cp is not None
    assert cp["last_sync"] is not None
    assert cp["error"] is None


def test_cancelled_sync_does_not_advance_last_sync(
    engine: SyncEngine,
    store: KnowledgeStore,
) -> None:
    """Disconnect cancellation is incomplete work, not a successful sync."""
    cancel_event = threading.Event()

    class CancellingConnector(StubConnector):
        connector_id = "cancel-watermark"

        def sync(self, **kwargs):
            yield _make_doc("kept")
            cancel_event.set()
            yield _make_doc("not-ingested")

    items = engine.sync(
        CancellingConnector([]),
        cancel_event=cancel_event,
    )

    assert items == 0
    assert store.count() == 0
    cp = engine.get_checkpoint("cancel-watermark")
    assert cp is not None
    assert cp["last_sync"] is None
