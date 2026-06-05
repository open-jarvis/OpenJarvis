from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.hybrid_search import HybridSearch
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.connectors.sync_engine import SyncEngine

MARKER = "OPENJARVIS_PERSONAL_MAIN_MARKER_001"


def test_hybrid_search_does_not_fallback_to_recent_rows_for_nonempty_query(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.db")
    store.store(
        MARKER,
        source="gmail",
        source_id="personal-main:msg-1",
        doc_type="email",
        doc_id="gmail:personal-main:msg-1",
        title="test",
        author="Nirav <nirav@example.com>",
        metadata={"account": "personal-main", "source_profile": "personal-main"},
        timestamp="2026-06-05T14:28:51-04:00",
    )
    store.store(
        "An unrelated work email",
        source="gmail",
        source_id="work-credain:msg-1",
        doc_type="email",
        doc_id="gmail:work-credain:msg-1",
        title="unrelated",
        author="Work <work@example.com>",
        metadata={"account": "work-credain", "source_profile": "work-credain"},
        timestamp="2026-06-05T14:29:00-04:00",
    )

    search = HybridSearch(store, embedder=None)

    personal_hits = search.search(MARKER, sources=["gmail:personal-main"])
    work_hits = search.search(MARKER, sources=["gmail:work-credain"])

    assert len(personal_hits) == 1
    assert personal_hits[0].account == "personal-main"
    assert MARKER in personal_hits[0].content_snippet
    assert work_hits == []


def test_research_agent_strips_account_alias_person_filter():
    from openjarvis.agents.research_loop import ResearchAgent

    class _FakeSearch:
        def __init__(self):
            self.calls = []

        def search(
            self,
            query,
            *,
            person=None,
            time_range=None,
            sources=None,
            accounts=None,
            limit=20,
        ):
            self.calls.append(
                {
                    "query": query,
                    "person": person,
                    "time_range": time_range,
                    "sources": sources,
                    "accounts": accounts,
                    "limit": limit,
                }
            )
            return []

    fake_search = _FakeSearch()
    agent = ResearchAgent(engine=None, search=fake_search)  # type: ignore[arg-type]

    agent._execute_search(
        {
            "query": MARKER,
            "person": "Personal Main",
            "sources": ["gmail:personal-main"],
        }
    )
    agent._execute_search(
        {
            "query": MARKER,
            "person": "work-credain",
            "sources": ["gmail"],
            "accounts": ["work-credain"],
        }
    )

    agent._execute_search(
        {
            "query": MARKER,
            "person": "OpenJarvis",
            "sources": ["gmail:personal-main"],
        }
    )

    assert fake_search.calls[0]["person"] is None
    assert fake_search.calls[1]["person"] is None
    assert fake_search.calls[2]["person"] is None


class _AccountConnector(BaseConnector):
    connector_id = "gmail"
    display_name = "Gmail"
    auth_type = "oauth"

    def __init__(self, account: str, marker: str):
        self._account = account
        self._marker = marker

    def is_connected(self) -> bool:
        return True

    def disconnect(self) -> None:
        return None

    def sync(self, *, since=None, cursor=None) -> Iterator[Document]:
        # If sync state is incorrectly shared across accounts, the second
        # account receives since from the first account and emits nothing.
        if since is not None:
            return iter(())
        return iter(
            [
                Document(
                    doc_id=f"gmail:{self._account}:msg-1",
                    source="gmail",
                    doc_type="email",
                    content=self._marker,
                    title=self._marker,
                    author=f"{self._account}@example.com",
                    timestamp=datetime(2026, 6, 5, tzinfo=timezone.utc),
                    metadata={
                        "account": self._account,
                        "source_profile": self._account,
                    },
                    source_id=f"{self._account}:msg-1",
                )
            ]
        )

    def sync_status(self) -> SyncStatus:
        return SyncStatus()


def test_sync_engine_checkpoints_are_account_scoped(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.db")
    engine = SyncEngine(
        IngestionPipeline(store=store),
        state_db=str(tmp_path / "sync_state.db"),
    )

    assert engine.sync(_AccountConnector("personal-main", "personal marker")) == 1
    assert engine.sync(_AccountConnector("work-credain", "work marker")) == 1

    assert engine.get_checkpoint("gmail:personal-main")["items_synced"] == 1
    assert engine.get_checkpoint("gmail:work-credain")["items_synced"] == 1
    assert engine.get_checkpoint("gmail") is None

    rows = store._conn.execute(
        """
        SELECT json_extract(metadata, '$.account') AS account, COUNT(*) AS count
        FROM knowledge_chunks
        WHERE source='gmail'
        GROUP BY json_extract(metadata, '$.account')
        ORDER BY account
        """
    ).fetchall()
    assert [(row["account"], row["count"]) for row in rows] == [
        ("personal-main", 1),
        ("work-credain", 1),
    ]


def test_sync_engine_applies_checkpoint_lookback(monkeypatch, tmp_path):
    seen_since = []

    class _RecordingConnector(_AccountConnector):
        def sync(self, *, since=None, cursor=None):
            seen_since.append(since)
            return iter(())

    monkeypatch.setenv("OPENJARVIS_SYNC_LOOKBACK_SECONDS", "3600")
    store = KnowledgeStore(tmp_path / "knowledge.db")
    engine = SyncEngine(
        IngestionPipeline(store=store),
        state_db=str(tmp_path / "sync_state.db"),
    )
    engine._conn.execute(
        """
        INSERT INTO sync_state (connector_id, items_synced, cursor, last_sync, error)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("gmail:personal-main", 1, None, "2026-06-05T20:00:00+00:00", None),
    )
    engine._conn.commit()

    engine.sync(_RecordingConnector("personal-main", "marker"))

    assert seen_since[0].isoformat() == "2026-06-05T19:00:00+00:00"
