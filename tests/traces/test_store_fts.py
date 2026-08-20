"""Tests for FTS5 cross-session search on TraceStore."""

from __future__ import annotations

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
