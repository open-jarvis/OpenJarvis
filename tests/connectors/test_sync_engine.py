"""Tests for SyncEngine — checkpoint/resume connector orchestration."""

from __future__ import annotations

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
