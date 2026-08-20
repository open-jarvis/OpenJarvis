"""Tests for openjarvis.learning.spec_search.external_adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.evals.core.types import EvalRecord
from openjarvis.learning.spec_search.external_adapter import (
    write_external_records_as_traces,
)
from openjarvis.traces.store import TraceStore


def _fake_records(n: int) -> list[EvalRecord]:
    return [
        EvalRecord(
            record_id=f"rec-{i}",
            problem=f"question {i}",
            reference=f"answer {i}",
            category="test-category",
            metadata={"difficulty": "hard"} if i % 2 else None,
        )
        for i in range(n)
    ]


def test_writes_one_trace_per_record(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.db")
    records = _fake_records(5)
    count = write_external_records_as_traces(
        store,
        records,
        source_name="testcorpus",
    )
    assert count == 5


def test_synthetic_trace_fields(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.db")
    write_external_records_as_traces(
        store,
        _fake_records(1),
        source_name="test",
    )
    # Use store.get() with known trace_id to retrieve the trace directly.
    t = store.get("ext-test-rec-0")
    assert t is not None
    assert t.trace_id == "ext-test-rec-0"
    assert t.query == "question 0"
    assert t.result == "answer 0"
    assert t.agent == "external"
    assert t.model == "external"
    assert t.engine == "external"
    assert t.steps == []
    assert t.outcome is None
    assert t.feedback == 0.5
    assert t.metadata["source"] == "test"
    assert t.metadata["record_id"] == "rec-0"


def test_custom_feedback_score(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.db")
    write_external_records_as_traces(
        store,
        _fake_records(1),
        source_name="src",
        feedback_score=0.9,
    )
    trace = store.get("ext-src-rec-0")
    assert trace is not None
    assert trace.feedback == 0.9


def test_metadata_merges_record_metadata(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.db")
    records = [
        EvalRecord(
            record_id="A",
            problem="q",
            reference="r",
            category="cat",
            metadata={"k1": "v1", "k2": "v2"},
        ),
    ]
    write_external_records_as_traces(store, records, source_name="src")
    trace = store.get("ext-src-A")
    assert trace is not None
    assert trace.metadata == {
        "source": "src",
        "record_id": "A",
        "k1": "v1",
        "k2": "v2",
    }


def test_written_traces_are_fts_searchable(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.db")
    records = [
        EvalRecord(
            record_id="alpha",
            problem="question about databases",
            reference="answer",
            category="cat",
        ),
        EvalRecord(
            record_id="beta",
            problem="question about networking",
            reference="answer",
            category="cat",
        ),
    ]
    write_external_records_as_traces(store, records, source_name="src")
    hits = store.search("databases", limit=10)
    assert any(h["query"] == "question about databases" for h in hits)


def test_returns_zero_for_empty_input(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.db")
    count = write_external_records_as_traces(
        store,
        [],
        source_name="empty",
    )
    assert count == 0


def test_duplicate_record_ids_raise(tmp_path: Path):
    import sqlite3

    store = TraceStore(tmp_path / "traces.db")
    records = [
        EvalRecord(record_id="dup", problem="p1", reference="r", category="cat"),
        EvalRecord(record_id="dup", problem="p2", reference="r", category="cat"),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        write_external_records_as_traces(store, records, source_name="src")
