"""Tests for HybridSearch account/profile filtering."""

from __future__ import annotations

from pathlib import Path

from openjarvis.connectors.hybrid_search import HybridSearch
from openjarvis.connectors.store import KnowledgeStore


def _store(ks: KnowledgeStore, **kwargs) -> str:  # type: ignore[type-arg]
    defaults = {
        "content": "project alpha update",
        "source": "gmail",
        "doc_type": "email",
        "doc_id": None,
        "title": "",
        "author": "",
        "participants": None,
        "timestamp": "2026-01-01T00:00:00",
        "thread_id": None,
        "url": None,
        "metadata": None,
        "chunk_index": 0,
    }
    defaults.update(kwargs)
    return ks.store(**defaults)  # type: ignore[call-arg]


def test_hybrid_search_filters_by_account_alias(tmp_path: Path) -> None:
    """accounts=['work'] narrows all matching connectors to that profile."""
    ks = KnowledgeStore(db_path=tmp_path / "knowledge.db")
    _store(
        ks,
        content="project alpha renewal from work inbox",
        title="Work renewal",
        doc_id="gmail:work:1",
        metadata={"account": "work", "source_profile": "work"},
    )
    _store(
        ks,
        content="project alpha renewal from personal inbox",
        title="Personal renewal",
        doc_id="gmail:personal:1",
        metadata={"account": "personal", "source_profile": "personal"},
        chunk_index=1,
    )

    hits = HybridSearch(ks).search("project alpha renewal", accounts=["work"])

    assert hits
    assert {h.title for h in hits} == {"Work renewal"}
    assert all(h.account == "work" for h in hits)
    assert all(h.source_profile == "work" for h in hits)


def test_hybrid_search_intersects_sources_and_accounts(tmp_path: Path) -> None:
    """Connector and account filters combine for precise persona-scoped queries."""
    ks = KnowledgeStore(db_path=tmp_path / "knowledge.db")
    _store(
        ks,
        content="project alpha roadmap in work Gmail",
        source="gmail",
        title="Work Gmail roadmap",
        doc_id="gmail:work:1",
        metadata={"account": "work", "source_profile": "work"},
    )
    _store(
        ks,
        content="project alpha roadmap in work Drive",
        source="gdrive",
        doc_type="file",
        title="Work Drive roadmap",
        doc_id="gdrive:work:1",
        metadata={"account": "work", "source_profile": "work"},
        chunk_index=1,
    )
    _store(
        ks,
        content="project alpha roadmap in personal Drive",
        source="gdrive",
        doc_type="file",
        title="Personal Drive roadmap",
        doc_id="gdrive:personal:1",
        metadata={"account": "personal", "source_profile": "personal"},
        chunk_index=2,
    )

    hits = HybridSearch(ks).search(
        "project alpha roadmap",
        sources=["gdrive"],
        accounts=["work"],
    )

    assert hits
    assert {h.title for h in hits} == {"Work Drive roadmap"}
    assert all(h.source == "gdrive" for h in hits)
    assert all(h.account == "work" for h in hits)
