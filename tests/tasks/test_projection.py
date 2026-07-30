from __future__ import annotations

from pathlib import Path

from openjarvis.codex.types import (
    CodexBackendKind,
    CodexEvent,
    CodexEventType,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.tasks import (
    CodexTaskEventProjector,
    TaskService,
    TaskStore,
)
from openjarvis.traces.store import TraceStore


def _event(
    event_id: str,
    sequence: int,
    event_type: CodexEventType,
    *,
    payload: dict | None = None,
    item_id: str | None = None,
) -> CodexEvent:
    return CodexEvent(
        event_id=event_id,
        sequence=sequence,
        occurred_at=f"2026-07-30T00:00:0{sequence}+00:00",
        task_id="task",
        session_id="session",
        thread_id="thread",
        turn_id="turn",
        item_id=item_id,
        backend=CodexBackendKind.PYTHON_SDK,
        event_type=event_type,
        payload=payload or {},
    )


def _runtime(
    tmp_path: Path,
) -> tuple[TaskStore, TraceStore, EventBus, CodexTaskEventProjector]:
    store = TaskStore(tmp_path / "runtime.db")
    TaskService(store).create(
        task_id="task",
        session_id="session",
        correlation_id="correlation",
        description="request",
        component="test",
        cause="user_request",
        idempotency_key="create",
    )
    traces = TraceStore(tmp_path / "traces.db")
    bus = EventBus(record_history=True)
    projector = CodexTaskEventProjector(store, bus=bus, trace_store=traces)
    return store, traces, bus, projector


def test_codex_event_roundtrips_to_timeline_trace_and_bus(tmp_path: Path) -> None:
    store, traces, bus, projector = _runtime(tmp_path)
    try:
        result = projector.project(
            _event(
                "source-1",
                1,
                CodexEventType.ITEM_STARTED,
                item_id="item",
                payload={"item": {"type": "agentMessage"}},
            )
        )

        assert result.inserted is True
        assert result.trace_projected is True
        assert result.event.sequence == 2
        assert store.list_items("task")[0].item_id == "item"
        assert traces.list_task_events("task")[0]["event_id"] == result.event.event_id
        assert len(bus.history) == 1
        assert bus.history[0].event_type is EventType.CODEX_EVENT
        assert bus.history[0].data["task_id"] == "task"
    finally:
        traces.close()
        store.close()


def test_duplicate_source_event_is_not_republished(tmp_path: Path) -> None:
    store, traces, bus, projector = _runtime(tmp_path)
    try:
        event = _event("source-1", 1, CodexEventType.TURN_STARTED)
        first = projector.project(event)
        repeated = projector.project(event)

        assert first.inserted is True
        assert repeated.inserted is False
        assert repeated.event == first.event
        assert len(store.list_task_events("task")) == 2
        assert len(traces.list_task_events("task")) == 1
        assert len(bus.history) == 1
    finally:
        traces.close()
        store.close()


def test_large_command_output_is_redacted_and_stored_as_artifact(
    tmp_path: Path,
) -> None:
    store, traces, bus, projector = _runtime(tmp_path)
    del bus
    try:
        result = projector.project(
            _event(
                "source-large",
                1,
                CodexEventType.COMMAND_OUTPUT,
                item_id="command-item",
                payload={
                    "output": "x" * 8_000,
                    "api_key": "must-not-survive",
                },
            )
        )

        assert result.artifact is not None
        assert result.event.artifact_id == result.artifact.artifact_id
        assert result.event.payload["truncated"] is True
        assert "must-not-survive" not in result.event.payload["preview"]
        content = store.read_artifact(result.artifact.artifact_id).decode("utf-8")
        assert "must-not-survive" not in content
        assert "[REDACTED]" in content
        trace_event = traces.list_task_events("task")[0]
        assert trace_event["artifact_id"] == result.artifact.artifact_id
        assert len(str(trace_event["payload"])) < 2_000
    finally:
        traces.close()
        store.close()


def test_late_event_is_appended_without_rewriting_state(tmp_path: Path) -> None:
    store, traces, bus, projector = _runtime(tmp_path)
    del bus
    try:
        projector.project(
            _event("newer", 2, CodexEventType.TURN_COMPLETED)
        )
        projector.project(
            _event("older", 1, CodexEventType.ITEM_STARTED, item_id="late-item")
        )

        events = store.list_task_events("task")
        assert [event.sequence for event in events] == [1, 2, 3]
        assert [event.event_type for event in events[1:]] == [
            "turn.completed",
            "item.started",
        ]
        task = store.get_task("task")
        assert task is not None
        assert task.status.value == "pending"
    finally:
        traces.close()
        store.close()
