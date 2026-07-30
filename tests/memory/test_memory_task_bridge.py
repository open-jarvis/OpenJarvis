"""Phase-3 task/source/trace correlation tests for memory retrieval."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_service import VaultMemoryService
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import ExecutionLane
from openjarvis.traces.store import TraceStore


def _write(path: Path, *, title: str, body: str) -> str:
    note_id = str(uuid.uuid4())
    path.write_text(
        "---\n"
        f"id: {note_id}\n"
        "schema_version: 1\n"
        "type: fact\n"
        "status: active\n"
        "scope: personal\n"
        "source: manual\n"
        f"title: {title}\n"
        "---\n"
        f"{body.rstrip()}\n",
        encoding="utf-8",
    )
    return note_id


@pytest.fixture()
def correlated(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    task_store = TaskStore(tmp_path / "tasks.sqlite3")
    trace_store = TraceStore(tmp_path / "traces.sqlite3")
    task_store.create_task(
        task_id="task-1",
        session_id="session-1",
        correlation_id="correlation-1",
        description="Retrieve synthetic memory",
        execution_lane=ExecutionLane.MODEL,
        backend="codex",
        risk_level=0,
        component="test",
        cause="user_request",
        idempotency_key="create-task-1",
    )
    index = VaultIndex(vault, tmp_path / "state" / "memory.sqlite3")
    bridge = MemoryTaskBridge(task_store, trace_store=trace_store)
    service = VaultMemoryService(index, task_bridge=bridge)
    context = MemoryTaskContext(
        task_id="task-1",
        session_id="session-1",
        correlation_id="correlation-1",
        thread_id="thread-1",
        turn_id="turn-1",
    )
    yield vault, service, task_store, trace_store, context
    service.close()
    task_store.close()
    trace_store.close()


def test_only_selected_sources_attach_to_canonical_task(correlated) -> None:
    vault, service, task_store, _trace_store, context = correlated
    for number in range(3):
        folder = vault / f"folder-{number}"
        folder.mkdir()
        _write(
            folder / "note.md",
            title=f"Python {number}",
            body=f"Python source {number}.",
        )
    service.rebuild(context=context)

    result = service.search("Python source", top_k=1, context=context)
    task_sources = task_store.list_sources("task-1")

    assert len(result.candidates) == 3
    assert len(result.selected_sources) == 1
    assert len(task_sources) == 1
    assert task_sources[0].source_id == result.selected_sources[0].source_id
    assert task_sources[0].metadata["note_id"] == result.selected_sources[0].note_id
    assert "relevant_preview" in task_sources[0].metadata


def test_memory_timeline_and_trace_events_are_correlated(correlated) -> None:
    vault, service, task_store, trace_store, context = correlated
    _write(vault / "note.md", title="Python", body="Python is the selected tool.")
    service.rebuild(context=context)

    result = service.search("selected Python", context=context)
    events = task_store.list_task_events("task-1")
    trace_events = trace_store.list_task_events("task-1")
    memory_events = [
        event for event in events if event.event_type.startswith("memory.")
    ]

    assert result.selected_sources
    assert {
        "memory.index_updated",
        "memory.query_started",
        "memory.candidate_found",
        "memory.source_selected",
    } <= {event.event_type for event in memory_events}
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert len(trace_events) == len(memory_events)
    selected = next(
        event for event in memory_events if event.event_type == "memory.source_selected"
    )
    assert selected.session_id == "session-1"
    assert selected.correlation_id == "correlation-1"
    assert selected.thread_id == "thread-1"
    assert selected.turn_id == "turn-1"
    assert selected.payload["retrieval_id"] == result.retrieval_id


def test_large_note_content_is_bounded_in_task_and_trace(correlated) -> None:
    vault, service, task_store, trace_store, context = correlated
    body = "needle evidence\n" + ("private synthetic filler " * 5000)
    _write(vault / "large.md", title="Large", body=body)
    service.rebuild()

    service.search("needle evidence", context=context)
    events = task_store.list_task_events("task-1")
    trace_events = trace_store.list_task_events("task-1")
    serialized = repr([dict(event.payload) for event in events])
    trace_serialized = repr(trace_events)

    assert len(serialized) < 6000
    assert len(trace_serialized) < 6000
    assert "private synthetic filler " * 100 not in serialized
    assert "private synthetic filler " * 100 not in trace_serialized


def test_insufficient_evidence_records_no_task_source(correlated) -> None:
    vault, service, task_store, _trace_store, context = correlated
    _write(vault / "known.md", title="Known", body="Only Python.")
    service.rebuild()

    result = service.search("quantum entanglement", context=context)
    events = task_store.list_task_events("task-1")

    assert result.evidence_code == "insufficient_evidence"
    assert task_store.list_sources("task-1") == []
    assert any(
        event.event_type == "memory.evidence_insufficient" for event in events
    )


def test_repeated_retrieval_id_is_exactly_once_in_task_store(correlated) -> None:
    vault, service, task_store, _trace_store, context = correlated
    _write(vault / "note.md", title="Python", body="Python source.")
    service.rebuild()

    first = service.search(
        "Python",
        context=context,
        retrieval_id="retrieval-idempotent",
    )
    event_count = len(task_store.list_task_events("task-1"))
    repeated = service.search(
        "Python",
        context=context,
        retrieval_id="retrieval-idempotent",
    )

    assert first.selected_sources == repeated.selected_sources
    assert len(task_store.list_sources("task-1")) == 1
    assert len(task_store.list_task_events("task-1")) == event_count


def test_context_must_match_canonical_task(correlated) -> None:
    vault, service, _task_store, _trace_store, _context = correlated
    _write(vault / "note.md", title="Python", body="Python source.")
    service.rebuild()
    wrong = MemoryTaskContext(
        task_id="task-1",
        session_id="wrong-session",
        correlation_id="correlation-1",
    )

    with pytest.raises(ValueError, match="session_id"):
        service.search("Python", context=wrong)
