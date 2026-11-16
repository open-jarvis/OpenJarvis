"""Tests for FTS5 cross-session search on TraceStore."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from openjarvis.core.types import Trace


@pytest.fixture
def store():
    from openjarvis.traces.store import TraceStore

    with tempfile.TemporaryDirectory() as tmpdir:
        s = TraceStore(Path(tmpdir) / "traces.db")
        yield s


def _make_trace(trace_id: str, query: str, result: str, agent: str = "test") -> Trace:
    return Trace(
        trace_id=trace_id,
        query=query,
        agent=agent,
        model="test-model",
        engine="test-engine",
        result=result,
        outcome="success",
        steps=[],
    )


class TestFTS5Search:
    def test_search_by_query(self, store):
        store.save(
            _make_trace(
                "t1",
                "find papers on reasoning",
                "found 3 papers",
                agent="researcher",
            )
        )
        store.save(
            _make_trace(
                "t2",
                "calculate 2+2",
                "4",
                agent="calculator",
            )
        )
        results = store.search("papers reasoning", agent="researcher")
        assert len(results) >= 1
        assert results[0]["trace_id"] == "t1"

    def test_search_by_result(self, store):
        store.save(
            _make_trace(
                "t1",
                "search",
                "discovered breakthrough in LLMs",
                agent="a",
            )
        )
        results = store.search("breakthrough LLMs")
        assert len(results) >= 1

    def test_search_agent_filter(self, store):
        store.save(
            _make_trace(
                "t1",
                "query about reasoning",
                "result",
                agent="agent_a",
            )
        )
        store.save(
            _make_trace(
                "t2",
                "query about reasoning",
                "result",
                agent="agent_b",
            )
        )
        results = store.search("reasoning", agent="agent_a")
        assert all(r["agent"] == "agent_a" for r in results)

    def test_search_empty(self, store):
        results = store.search("nonexistent gibberish xyzzy")
        assert results == []

    @pytest.mark.parametrize(
        "query",
        [
            "Alice's error",
            "When did task-101 fail?",
            "task-101",
            "fix-traces-fts",
        ],
    )
    def test_search_accepts_plain_text_punctuation(self, store, query):
        store.save(
            _make_trace(
                "t_punct",
                "investigate Alice's error in task-101",
                "fixed by fix-traces-fts",
                agent="debugger",
            )
        )
        results = store.search(query)
        assert any(r["trace_id"] == "t_punct" for r in results)

    def test_search_accepts_symbol_heavy_terms(self, store):
        store.save(
            _make_trace(
                "t_cpp",
                "The C++ migration guide",
                "success",
                agent="coder",
            )
        )
        assert store.search("C++")
        assert store.search("++") == []

    def test_search_empty_and_punctuation_only(self, store):
        assert store.search("") == []
        assert store.search("   ") == []
        assert store.search("---") == []
        assert store.search("???") == []

    def test_search_surfaces_database_errors(self, store):
        store._conn.execute("DROP TABLE traces_fts")

        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            store.search("trace")


class TestFTSDeleteSync:
    """The delete half of the external-content sync pair.

    Without an AFTER DELETE trigger a removed trace keeps its index entry:
    its tokens stay matchable and reads through the index fail with
    "missing row N from content table".
    """

    def test_deleted_trace_is_not_matchable(self, store):
        store.save(_make_trace("t1", "my private medical question", "the answer"))
        store.save(_make_trace("t2", "an unrelated kitchen question", "other"))

        store._conn.execute("DELETE FROM traces WHERE trace_id = 't1'")
        store._conn.commit()

        rows = store._conn.execute(
            "SELECT rowid FROM traces_fts WHERE traces_fts MATCH 'medical'"
        ).fetchall()
        assert rows == []

        # The surviving trace is untouched.
        rows = store._conn.execute(
            "SELECT rowid FROM traces_fts WHERE traces_fts MATCH 'kitchen'"
        ).fetchall()
        assert len(rows) == 1

    def test_indexed_columns_remain_readable_after_delete(self, store):
        """A stale entry makes reads through the index raise.

        ``TraceStore.search`` joins back to ``traces`` and so silently skips
        an orphaned index row; reading the indexed columns straight from
        ``traces_fts`` is what surfaces the inconsistency, with
        "missing row N from content table".
        """
        store.save(_make_trace("t1", "first question", "first answer"))
        store.save(_make_trace("t2", "second question", "second answer"))

        store._conn.execute("DELETE FROM traces WHERE trace_id = 't1'")
        store._conn.commit()

        rows = store._conn.execute(
            "SELECT query FROM traces_fts WHERE traces_fts MATCH 'question'"
        ).fetchall()
        assert [r[0] for r in rows] == ["second question"]

        # The public search path keeps working too.
        assert [r["trace_id"] for r in store.search("question")] == ["t2"]

    def test_update_of_indexed_column_reindexes(self, store):
        store.save(_make_trace("t1", "original wording", "result"))

        store._conn.execute(
            "UPDATE traces SET query = 'replacement wording' WHERE trace_id = 't1'"
        )
        store._conn.commit()

        assert (
            store._conn.execute(
                "SELECT rowid FROM traces_fts WHERE traces_fts MATCH 'original'"
            ).fetchall()
            == []
        )
        assert (
            len(
                store._conn.execute(
                    "SELECT rowid FROM traces_fts WHERE traces_fts MATCH 'replacement'"
                ).fetchall()
            )
            == 1
        )

    def test_stale_index_from_an_older_database_is_rebuilt(self, tmp_path):
        """A database written before the triggers existed is repaired on open."""
        from openjarvis.traces.store import (
            _CREATE_FTS,
            _CREATE_STEPS,
            _CREATE_TRACES,
            _FTS_SYNC_INSERT,
            TraceStore,
        )

        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        for stmt in (_CREATE_TRACES, _CREATE_STEPS, _CREATE_FTS, _FTS_SYNC_INSERT):
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO traces (trace_id, query, agent, result) "
            "VALUES ('old', 'leftover secret', 'a', 'r')"
        )
        conn.execute("DELETE FROM traces")
        conn.commit()
        # The pre-fix state: row gone, token still indexed.
        assert conn.execute(
            "SELECT rowid FROM traces_fts WHERE traces_fts MATCH 'leftover'"
        ).fetchall()
        conn.close()

        TraceStore(db)  # opening it runs the one-time rebuild

        conn = sqlite3.connect(str(db))
        assert (
            conn.execute(
                "SELECT rowid FROM traces_fts WHERE traces_fts MATCH 'leftover'"
            ).fetchall()
            == []
        )
        conn.close()
