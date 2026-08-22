"""Tests for toast-1-backed research retrieval (MixedbreadSearch + sync).

Same approach as the MixedbreadMemory backend tests: the classes are
adapters over the ``mixedbread`` SDK, so a fake client exercises argument
mapping, local hydration, filter semantics, fallback behavior, and sync
idempotency offline. Skipped when the optional SDK is not installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

pytest.importorskip("mixedbread")

from openjarvis.connectors.hybrid_search import (  # noqa: E402
    HybridSearch,
    build_research_search,
)
from openjarvis.connectors.mixedbread_search import (  # noqa: E402
    MIRROR_METADATA_KEY,
    MixedbreadKnowledgeSync,
    MixedbreadSearch,
)
from openjarvis.connectors.store import KnowledgeStore  # noqa: E402
from openjarvis.core.config import JarvisConfig  # noqa: E402


def _chunk(
    *,
    external_id: Optional[str],
    text: str = "remote text",
    score: float = 0.9,
    file_id: str = "file_1",
    filename: str = "chunk.md",
    chunk_index: int = 0,
    metadata: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        external_id=external_id,
        text=text,
        score=score,
        file_id=file_id,
        filename=filename,
        chunk_index=chunk_index,
        metadata=metadata,
    )


class FakeStores:
    def __init__(self) -> None:
        self.files = self
        self.search_results: List[SimpleNamespace] = []
        self.search_calls: List[Dict[str, Any]] = []
        self.upload_calls: List[Dict[str, Any]] = []
        self.list_calls: List[Dict[str, Any]] = []
        self.delete_calls: List[tuple[str, str]] = []
        self.remote_pages: List[List[SimpleNamespace]] = [[]]
        self.search_error: Optional[Exception] = None

    def retrieve(self, store_identifier: str) -> SimpleNamespace:
        return SimpleNamespace(id="kstore_1")

    def search(self, **kwargs: Any) -> SimpleNamespace:
        self.search_calls.append(kwargs)
        if self.search_error is not None:
            raise self.search_error
        return SimpleNamespace(data=list(self.search_results))

    def upload(self, **kwargs: Any) -> SimpleNamespace:
        self.upload_calls.append(kwargs)
        return SimpleNamespace(id=f"file_{len(self.upload_calls)}")

    def list(self, **kwargs: Any) -> SimpleNamespace:
        self.list_calls.append(kwargs)
        after = kwargs.get("after")
        page_index = int(str(after).split("-")[-1]) if after else 0
        has_more = page_index + 1 < len(self.remote_pages)
        return SimpleNamespace(
            data=list(self.remote_pages[page_index]),
            pagination=SimpleNamespace(
                has_more=has_more,
                last_cursor=f"page-{page_index + 1}" if has_more else None,
            ),
        )

    def delete(self, file_identifier: str, *, store_identifier: str) -> None:
        self.delete_calls.append((file_identifier, store_identifier))


class FakeClient:
    def __init__(self) -> None:
        self.stores = FakeStores()
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _seed(store: KnowledgeStore, content: str, *, source: str = "gmail", **kw) -> str:
    return store.store(
        content=content, source=source, doc_id=f"doc-{content[:8]}", **kw
    )


def test_search_hydrates_local_rows_in_remote_rank_order() -> None:
    store = KnowledgeStore(db_path=":memory:")
    id_a = _seed(store, "Quarterly revenue grew twelve percent.", title="Q3 report")
    id_b = _seed(store, "The offsite is in Lisbon this year.", title="Offsite plan")

    client = FakeClient()
    client.stores.search_results = [
        _chunk(external_id=id_b, score=0.95),
        _chunk(external_id=id_a, score=0.60),
    ]
    search = MixedbreadSearch(store, client=client)

    hits = search.search("where is the offsite?", limit=5)

    assert [h.chunk_id for h in hits] == [id_b, id_a]
    assert hits[0].title == "Offsite plan"
    assert "Lisbon" in hits[0].content_snippet
    assert hits[0].score == pytest.approx(0.95)
    assert hits[0].source == "gmail"

    (call,) = client.stores.search_calls
    assert call["store_identifiers"] == ["kstore_1"]
    assert call["top_k"] == 15  # limit * default overfetch of 3
    assert call["search_options"]["agentic"] is True


def test_search_applies_structured_filters_locally() -> None:
    store = KnowledgeStore(db_path=":memory:")
    id_mail = _seed(store, "Mail about the launch date.", source="gmail")
    id_slack = _seed(store, "Slack chatter about the launch.", source="slack")

    client = FakeClient()
    client.stores.search_results = [
        _chunk(external_id=id_slack, score=0.9),
        _chunk(external_id=id_mail, score=0.8),
    ]
    search = MixedbreadSearch(store, client=client)

    hits = search.search("launch date", sources=["gmail"], limit=5)

    assert [h.chunk_id for h in hits] == [id_mail]


def test_search_applies_person_and_time_filters_via_public_store_api() -> None:
    store = KnowledgeStore(db_path=":memory:")
    id_match = _seed(
        store,
        "Alice approved the launch.",
        participants=["alice@example.com"],
        timestamp="2026-08-20T12:00:00+00:00",
    )
    id_old = _seed(
        store,
        "Alice discussed the old launch.",
        participants=["alice@example.com"],
        timestamp="2025-08-20T12:00:00+00:00",
    )
    id_other = _seed(
        store,
        "Bob approved the launch.",
        participants=["bob@example.com"],
        timestamp="2026-08-20T12:00:00+00:00",
    )
    client = FakeClient()
    client.stores.search_results = [
        _chunk(external_id=id_old, score=0.95),
        _chunk(external_id=id_other, score=0.90),
        _chunk(external_id=id_match, score=0.85),
    ]
    search = MixedbreadSearch(store, client=client)

    hits = search.search(
        "launch",
        person="alice",
        time_range=(datetime(2026, 1, 1, tzinfo=timezone.utc), None),
    )

    assert [hit.chunk_id for hit in hits] == [id_match]


def test_search_does_not_hydrate_a_locally_deleted_chunk() -> None:
    store = KnowledgeStore(db_path=":memory:")
    chunk_id = _seed(store, "Delete before searching.")
    store._conn.execute(
        "UPDATE knowledge_chunks SET deleted_at = 1.0 WHERE id = ?", (chunk_id,)
    )

    client = FakeClient()
    client.stores.search_results = [_chunk(external_id=chunk_id)]
    search = MixedbreadSearch(store, client=client)

    assert search.search("deleted", limit=5) == []


def test_search_falls_back_to_hybrid_on_api_error() -> None:
    store = KnowledgeStore(db_path=":memory:")
    _seed(store, "The telemetry cluster SLA is now 99.95 percent.")

    client = FakeClient()
    client.stores.search_error = RuntimeError("api down")
    fallback = HybridSearch(store, None)
    search = MixedbreadSearch(store, client=client, fallback=fallback)

    hits = search.search("telemetry SLA", limit=5)

    assert hits, "fallback should serve results when the API fails"
    assert "99.95" in hits[0].content_snippet


def test_search_error_without_fallback_propagates() -> None:
    store = KnowledgeStore(db_path=":memory:")
    client = FakeClient()
    client.stores.search_error = RuntimeError("api down")
    search = MixedbreadSearch(store, client=client)

    with pytest.raises(RuntimeError, match="api down"):
        search.search("anything")


def test_empty_query_delegates_to_fallback_not_api() -> None:
    store = KnowledgeStore(db_path=":memory:")
    _seed(store, "Recent snapshot row.")

    client = FakeClient()
    search = MixedbreadSearch(store, client=client, fallback=HybridSearch(store, None))

    hits = search.search("   ", limit=5)

    assert hits, "metadata-only query should hit the local fallback"
    assert client.stores.search_calls == []


def test_unmatched_remote_file_synthesizes_hit_only_unfiltered() -> None:
    store = KnowledgeStore(db_path=":memory:")
    client = FakeClient()
    client.stores.search_results = [
        _chunk(
            external_id=None,
            text="Directly uploaded doc.",
            filename="direct.md",
            metadata={"source": "upload"},
        ),
    ]
    search = MixedbreadSearch(store, client=client)

    hits = search.search("direct", limit=5)
    assert len(hits) == 1
    assert hits[0].source == "upload"
    assert hits[0].title == "direct.md"

    # With structured filters we cannot verify the remote-only file, so
    # it must be suppressed rather than bypass the filter.
    assert search.search("direct", sources=["gmail"], limit=5) == []


def test_sync_uploads_live_chunks_idempotently() -> None:
    store = KnowledgeStore(db_path=":memory:")
    id_a = _seed(store, "Keep me.", title="A")
    id_b = _seed(store, "Keep me too.", title="B")
    id_gone = _seed(store, "Soft deleted.", title="C")
    store._conn.execute(
        "UPDATE knowledge_chunks SET deleted_at = 1.0 WHERE id = ?", (id_gone,)
    )

    client = FakeClient()
    sync = MixedbreadKnowledgeSync(store, client=client)

    dry = sync.sync(dry_run=True)
    assert (dry.total, dry.uploaded, dry.dry_run) == (2, 0, True)
    assert client.stores.upload_calls == []

    report = sync.sync()
    assert (report.total, report.uploaded, report.failed) == (2, 2, 0)
    by_ext = {c["external_id"]: c for c in client.stores.upload_calls}
    assert set(by_ext) == {id_a, id_b}
    call = by_ext[id_a]
    assert call["overwrite"] is True
    assert call["store_identifier"] == "kstore_1"
    filename, payload = call["file"]
    assert filename == f"{id_a}.md"
    body = payload.decode("utf-8")
    assert "# A" in body and "Keep me." in body
    assert call["metadata"]["source"] == "gmail"
    assert call["metadata"][MIRROR_METADATA_KEY] is True


def test_sync_deletes_only_stale_mirror_files_across_pages() -> None:
    store = KnowledgeStore(db_path=":memory:")
    live_id = _seed(store, "Still live.")
    client = FakeClient()
    client.stores.remote_pages = [
        [
            SimpleNamespace(
                id="remote-live",
                external_id=live_id,
                metadata={MIRROR_METADATA_KEY: True},
            ),
            SimpleNamespace(
                id="direct-upload",
                external_id="user-managed",
                metadata={"source": "upload"},
            ),
        ],
        [
            SimpleNamespace(
                id="remote-stale",
                external_id="deleted-local-chunk",
                metadata={MIRROR_METADATA_KEY: True},
            )
        ],
    ]

    report = MixedbreadKnowledgeSync(store, client=client).sync()

    assert report.deleted == 1
    assert report.delete_failed == 0
    assert client.stores.delete_calls == [("remote-stale", "kstore_1")]
    assert [call.get("after") for call in client.stores.list_calls] == [None, "page-1"]


def test_search_closes_only_an_owned_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from openjarvis.connectors import mixedbread_search as module

    store = KnowledgeStore(db_path=":memory:")
    owned = FakeClient()
    monkeypatch.setattr(module, "_build_client", lambda api_key: owned)
    search = module.MixedbreadSearch(store, api_key="test")

    search.close()
    search.close()
    assert owned.close_calls == 1

    injected = FakeClient()
    module.MixedbreadSearch(store, client=injected).close()
    assert injected.close_calls == 0


def test_build_research_search_defaults_to_hybrid() -> None:
    store = KnowledgeStore(db_path=":memory:")
    search = build_research_search(store, None, JarvisConfig())
    assert isinstance(search, HybridSearch)


def test_build_research_search_without_key_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MXBAI_API_KEY", raising=False)
    store = KnowledgeStore(db_path=":memory:")
    config = JarvisConfig()
    config.deep_research.retrieval = "mixedbread"

    search = build_research_search(store, None, config)

    assert isinstance(search, HybridSearch)


def test_build_research_search_mixedbread_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MXBAI_API_KEY", "test-key")
    store = KnowledgeStore(db_path=":memory:")
    config = JarvisConfig()
    config.deep_research.retrieval = "mixedbread"
    config.deep_research.mixedbread_store = "custom-store"

    search = build_research_search(store, None, config)

    assert isinstance(search, MixedbreadSearch)
    assert search._store_name == "custom-store"
    assert search._store is store  # ResearchAgent reads ._store for sources
    assert isinstance(search._fallback, HybridSearch)
