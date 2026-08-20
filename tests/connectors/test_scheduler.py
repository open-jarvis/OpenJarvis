"""Tests for SyncScheduler — periodic incremental sync background thread."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import pytest

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.scheduler import SyncScheduler
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.connectors.sync_engine import SyncEngine

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class _FakeConnector(BaseConnector):
    """A minimal connector that yields a fixed number of documents."""

    display_name = "Fake Scheduler Connector"
    auth_type = "filesystem"

    def __init__(
        self,
        connector_id: str = "fake_sched",
        *,
        connected: bool = True,
        doc_count: int = 2,
    ) -> None:
        self.connector_id = connector_id  # type: ignore[misc]
        self._connected = connected
        self._doc_count = doc_count

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        for i in range(self._doc_count):
            yield Document(
                doc_id=f"{self.connector_id}:{i}",
                source=self.connector_id,
                doc_type="note",
                content=f"Scheduled sync document {self.connector_id}:{i}.",
                title=f"Doc {i}",
            )

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=self._doc_count)


@pytest.fixture()
def engine(tmp_path: Path) -> SyncEngine:
    """Return a SyncEngine backed by in-memory stores."""
    store = KnowledgeStore(db_path=":memory:")
    pipeline = IngestionPipeline(store)
    return SyncEngine(pipeline, state_db=str(tmp_path / "state.db"))


# ---------------------------------------------------------------------------
# Test 1: add + run_once syncs a connected connector
# ---------------------------------------------------------------------------


def test_run_once_syncs_connected_connector(engine: SyncEngine) -> None:
    """run_once() calls engine.sync() for a connected connector."""
    conn = _FakeConnector("conn_single", connected=True, doc_count=3)
    scheduler = SyncScheduler(engine, interval_seconds=3600)
    scheduler.add(conn)

    results = scheduler.run_once()

    assert conn.connector_id in results
    assert results[conn.connector_id] == 3


# ---------------------------------------------------------------------------
# Test 2: run_once skips disconnected connectors
# ---------------------------------------------------------------------------


def test_run_once_skips_disconnected_connector(engine: SyncEngine) -> None:
    """run_once() does not attempt to sync a disconnected connector."""
    connected = _FakeConnector("conn_yes", connected=True, doc_count=1)
    disconnected = _FakeConnector("conn_no", connected=False, doc_count=5)

    scheduler = SyncScheduler(engine, interval_seconds=3600)
    scheduler.add(connected)
    scheduler.add(disconnected)

    results = scheduler.run_once()

    assert "conn_yes" in results
    assert "conn_no" not in results


# ---------------------------------------------------------------------------
# Test 3: start/stop does not crash
# ---------------------------------------------------------------------------


def test_start_stop_does_not_crash(engine: SyncEngine) -> None:
    """start() and stop() complete without error even with no connectors."""
    scheduler = SyncScheduler(engine, interval_seconds=60)
    scheduler.start()
    assert scheduler._thread is not None
    assert scheduler._thread.is_alive()
    scheduler.stop()
    # After stop the internal thread reference is cleared
    assert scheduler._thread is None


# ---------------------------------------------------------------------------
# Test 4: run_once returns chunk counts per connector
# ---------------------------------------------------------------------------


def test_run_once_returns_chunk_counts(engine: SyncEngine) -> None:
    """run_once() returns a mapping of connector_id → chunks ingested."""
    conn_a = _FakeConnector("conn_a", connected=True, doc_count=2)
    conn_b = _FakeConnector("conn_b", connected=True, doc_count=4)

    scheduler = SyncScheduler(engine, interval_seconds=3600)
    scheduler.add(conn_a)
    scheduler.add(conn_b)

    results = scheduler.run_once()

    assert results["conn_a"] == 2
    assert results["conn_b"] == 4
    assert len(results) == 2
