"""Tests for ProfileInjector / SessionRecallInjector / ToolAffinityInjector."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from openjarvis.personalization.injector import (
    ProfileInjector,
    SessionRecallInjector,
    ToolAffinityInjector,
)
from openjarvis.personalization.profile import UserProfile
from openjarvis.personalization.recall import SessionRecaller
from openjarvis.personalization.tool_affinity import ToolAffinityTracker

# ---------------------------------------------------------------------------
# ProfileInjector
# ---------------------------------------------------------------------------


def test_profile_injector_appends_known_facts() -> None:
    p = UserProfile()
    p.add("user.name", "Mac")
    p.add("pref.coffee", "黑咖啡")

    injector = ProfileInjector(profile=p)
    out = injector("你是 Jarvis。")
    assert out is not None
    assert "你是 Jarvis。" in out
    assert "[我知道關於你]" in out
    assert "user.name: Mac" in out
    assert "pref.coffee: 黑咖啡" in out


def test_profile_injector_skips_when_profile_empty() -> None:
    injector = ProfileInjector(profile=UserProfile())
    assert injector("你是 Jarvis。") == "你是 Jarvis。"


def test_profile_injector_passes_through_none() -> None:
    injector = ProfileInjector(profile=UserProfile())
    assert injector(None) is None


def test_profile_injector_respects_max_entries() -> None:
    p = UserProfile()
    for i in range(50):
        p.add(f"fact.f{i}", f"value{i}")
    injector = ProfileInjector(profile=p, max_entries=3)
    out = injector("base")
    assert out.count("fact.f") == 3


def test_profile_injector_reloads_from_disk(tmp_path: Path) -> None:
    profile_path = tmp_path / "USER.md"
    p = UserProfile()
    p.add("user.name", "Mac")
    p.save(profile_path)

    injector = ProfileInjector(profile_path=profile_path)
    out = injector("base")
    assert "Mac" in out


# ---------------------------------------------------------------------------
# SessionRecaller + SessionRecallInjector
# ---------------------------------------------------------------------------


def _seed_sessions_db(path: Path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE session_messages ("
        "  id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
        "  content TEXT, channel TEXT DEFAULT '', timestamp REAL,"
        "  metadata TEXT DEFAULT '{}'"
        ")"
    )
    for sid, role, content, ts in rows:
        conn.execute(
            "INSERT INTO session_messages (session_id, role, content, timestamp)"
            " VALUES (?, ?, ?, ?)",
            (sid, role, content, ts),
        )
    conn.commit()
    conn.close()


def test_session_recaller_finds_overlapping_turn(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    _seed_sessions_db(
        db,
        [
            ("s1", "user", "我喜歡黑咖啡不加糖", time.time() - 100),
            ("s1", "assistant", "好喔記下了", time.time() - 99),
            ("s2", "user", "今天天氣不錯", time.time() - 50),
        ],
    )
    recaller = SessionRecaller(db_path=db, min_score=0.0)
    hints = recaller.recall("我想再喝一杯黑咖啡", limit=2)
    assert hints
    assert any("黑咖啡" in h for h in hints)


def test_session_recaller_returns_empty_when_db_missing(tmp_path: Path) -> None:
    recaller = SessionRecaller(db_path=tmp_path / "missing.db")
    assert recaller.recall("anything") == []


def test_session_recaller_excludes_current_session(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    _seed_sessions_db(
        db,
        [
            ("current", "user", "我喜歡黑咖啡", time.time()),
            ("old", "user", "我喜歡黑咖啡", time.time() - 1000),
        ],
    )
    recaller = SessionRecaller(db_path=db).for_session("current")
    turns = recaller.recall_turns("黑咖啡")
    assert all(t.session_id != "current" for t in turns)


def test_session_recall_injector_attaches_block(tmp_path: Path) -> None:
    class _Stub:
        def recall(self, query, *, limit):
            return ["你曾說過：「我喜歡黑咖啡」"]

    injector = SessionRecallInjector(recaller=_Stub(), query="再來一杯")
    out = injector("base")
    assert "[過去對話線索]" in out
    assert "黑咖啡" in out


def test_session_recall_injector_skips_without_query() -> None:
    class _Stub:
        def recall(self, query, *, limit):  # pragma: no cover
            raise AssertionError("should not be called")

    injector = SessionRecallInjector(recaller=_Stub())
    assert injector("base") == "base"


# ---------------------------------------------------------------------------
# ToolAffinityTracker + ToolAffinityInjector
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker(tmp_path: Path) -> ToolAffinityTracker:
    return ToolAffinityTracker(db_path=tmp_path / "affinity.db")


def test_tool_affinity_records_and_ranks(tracker: ToolAffinityTracker) -> None:
    for _ in range(5):
        tracker.record("web_search", success=True)
    tracker.record("web_search", success=False)
    for _ in range(2):
        tracker.record("calculator", success=True)

    top = tracker.top_tools(limit=5)
    names = [n for n, *_ in top]
    assert names[0] == "web_search"
    rate = dict((n, r) for n, _c, r in top)
    assert rate["web_search"] == pytest.approx(5 / 6)


def test_tool_affinity_recent_window(tracker: ToolAffinityTracker) -> None:
    tracker.record("old_tool", success=True)
    # Force its last_used into the past.
    with sqlite3.connect(str(tracker._db_path)) as conn:
        conn.execute(
            "UPDATE tool_affinity SET last_used = ? WHERE tool_name = ?",
            (time.time() - 86400 * 30, "old_tool"),
        )
        conn.commit()
    tracker.record("fresh_tool", success=True)

    top_recent = tracker.top_tools(limit=5, recent_days=7)
    names = [n for n, *_ in top_recent]
    assert "old_tool" not in names
    assert "fresh_tool" in names


def test_tool_affinity_injector(tracker: ToolAffinityTracker) -> None:
    tracker.record("web_search", success=True)
    tracker.record("calculator", success=True)
    injector = ToolAffinityInjector(tracker=tracker, top_n=5)
    out = injector("base")
    assert "[你常用的工具]" in out
    assert "web_search" in out
    assert "calculator" in out
