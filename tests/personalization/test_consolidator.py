"""Tests for ProfileConsolidator."""

from __future__ import annotations

from openjarvis.personalization.consolidator import ProfileConsolidator
from openjarvis.tools.storage._stubs import RetrievalResult


class _FakeBackend:
    """In-memory stand-in that mimics SQLiteMemory.retrieve()."""

    def __init__(self, rows):
        # rows: list[dict] with keys: id, content, metadata
        self._rows = rows

    def all_documents(self):
        return list(self._rows)


def test_consolidator_groups_by_key_prefix(tmp_path) -> None:
    rows = [
        {
            "metadata": {"id": "1", "key": "user.name", "created_at": 100.0},
            "content": "Mac",
        },
        {
            "metadata": {"id": "2", "key": "pref.coffee", "created_at": 110.0},
            "content": "黑咖啡",
        },
        {
            "metadata": {"id": "3", "key": "fact.work", "created_at": 120.0},
            "content": "賈維斯維護者",
        },
    ]
    profile, stats = ProfileConsolidator(_FakeBackend(rows)).consolidate(
        output_path=tmp_path / "USER.md",
    )
    assert stats.accepted == 3
    assert stats.scanned == 3
    assert profile.get("user.name") == "Mac"
    assert profile.get("pref.coffee") == "黑咖啡"
    assert (tmp_path / "USER.md").exists()


def test_consolidator_latest_wins(tmp_path) -> None:
    rows = [
        {
            "metadata": {"id": "1", "key": "pref.lang", "created_at": 100.0},
            "content": "English",
        },
        {
            "metadata": {"id": "2", "key": "pref.lang", "created_at": 200.0},
            "content": "繁體中文",
        },
    ]
    profile, stats = ProfileConsolidator(_FakeBackend(rows)).consolidate(
        output_path=tmp_path / "USER.md",
    )
    assert profile.get("pref.lang") == "繁體中文"
    assert stats.skipped_duplicate == 1


def test_consolidator_skips_rows_without_key(tmp_path) -> None:
    rows = [
        {"metadata": {"id": "1"}, "content": "untyped RAG content"},
        {
            "metadata": {"id": "2", "key": "user.name", "created_at": 100.0},
            "content": "Mac",
        },
    ]
    _, stats = ProfileConsolidator(_FakeBackend(rows)).consolidate(
        output_path=tmp_path / "USER.md",
    )
    assert stats.skipped_no_key == 1
    assert stats.accepted == 1


def test_consolidator_handles_retrieval_result_objects(tmp_path) -> None:
    rows = [
        RetrievalResult(
            content="Mac",
            metadata={"id": "r1", "key": "user.name", "created_at": 1.0},
        ),
        RetrievalResult(
            content="黑咖啡",
            metadata={"id": "r2", "key": "pref.coffee", "created_at": 2.0},
        ),
    ]
    profile, stats = ProfileConsolidator(_FakeBackend(rows)).consolidate(
        output_path=tmp_path / "USER.md",
    )
    assert stats.accepted == 2
    assert profile.get("user.name") == "Mac"


def test_consolidator_falls_back_to_retrieve_when_no_enumerate(tmp_path) -> None:
    class _RetrieveOnly:
        def __init__(self, rows):
            self._rows = rows

        def retrieve(self, query, top_k=5):
            # Return everything regardless of query — simulates a backend
            # that doesn't expose an enumeration API.
            return [
                RetrievalResult(
                    content=r["content"],
                    metadata=r["metadata"],
                )
                for r in self._rows
            ]

    rows = [
        {
            "metadata": {"id": "1", "key": "user.name", "created_at": 1.0},
            "content": "Mac",
        }
    ]
    profile, stats = ProfileConsolidator(_RetrieveOnly(rows)).consolidate(
        output_path=tmp_path / "USER.md",
    )
    assert profile.get("user.name") == "Mac"
    # Each of the 5 prefix queries returns the same row → dedup via id.
    assert stats.accepted == 1
