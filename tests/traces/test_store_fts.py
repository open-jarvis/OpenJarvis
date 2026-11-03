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
        try:
            yield s
        finally:
            # Windows cannot delete the temp dir while the SQLite file is open.
            s.close()


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
