from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.tasks import TaskIdentity, TaskService, TaskStore


def _service(tmp_path: Path) -> tuple[TaskService, TaskStore]:
    store = TaskStore(tmp_path / "runtime.db")
    return TaskService(store), store


def test_identity_propagates_every_supported_id() -> None:
    base = TaskIdentity("task", "session", "correlation").validated()
    full = base.with_ids(
        thread_id="thread",
        turn_id="turn",
        item_id="item",
        approval_id="approval",
        action_id="action",
        artifact_id="artifact",
    )
    assert full.as_dict() == {
        "task_id": "task",
        "session_id": "session",
        "correlation_id": "correlation",
        "thread_id": "thread",
        "turn_id": "turn",
        "item_id": "item",
        "approval_id": "approval",
        "action_id": "action",
        "artifact_id": "artifact",
    }


def test_blank_optional_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        TaskIdentity("task", "session", "correlation", turn_id=" ").validated()


def test_task_sources_are_idempotent_and_owned(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    try:
        task = service.create(
            task_id="task",
            session_id="session",
            correlation_id="correlation",
            description="request",
            component="api",
            cause="user_request",
            idempotency_key="create",
        )
        first = store.add_source(
            task.task_id,
            source_kind="local_api",
            external_id="request-1",
            metadata={"channel": "desktop"},
        )
        repeated = store.add_source(
            task.task_id,
            source_kind="local_api",
            external_id="request-1",
            metadata={"ignored": True},
        )
        assert repeated == first
        assert store.list_sources(task.task_id) == [first]

        other = service.create(
            task_id="other",
            session_id="session",
            correlation_id="other-correlation",
            description="request",
            component="api",
            cause="user_request",
            idempotency_key="other-create",
        )
        with pytest.raises(ValueError):
            store.add_source(
                other.task_id,
                source_kind="local_api",
                external_id="request-1",
            )
    finally:
        store.close()


def test_task_thread_turn_item_correlation_roundtrip(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    try:
        task = service.create(
            task_id="task",
            session_id="session",
            correlation_id="correlation",
            description="request",
            component="api",
            cause="user_request",
            idempotency_key="create",
        )
        item = store.save_item(
            item_id="item",
            task_id=task.task_id,
            session_id=task.session_id,
            thread_id="thread",
            turn_id="turn",
            item_type="commandExecution",
            status="started",
            sequence=1,
            source_event_id="codex-event-1",
            payload={"command": "safe"},
        )
        updated = store.save_item(
            item_id="item",
            task_id=task.task_id,
            session_id=task.session_id,
            thread_id="thread",
            turn_id="turn",
            item_type="commandExecution",
            status="completed",
            sequence=1,
            source_event_id="codex-event-1",
            payload={"exit_code": 0},
        )

        assert item.task_id == task.task_id
        assert updated.status == "completed"
        assert store.list_items(task.task_id, turn_id="turn") == [updated]
    finally:
        store.close()


def test_external_event_is_ordered_and_deduplicated(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    try:
        task = service.create(
            task_id="task",
            session_id="session",
            correlation_id="correlation",
            description="request",
            component="api",
            cause="user_request",
            idempotency_key="create",
        )
        first, inserted = store.append_event(
            task_id=task.task_id,
            source_event_id="codex-event",
            event_type="turn.started",
            occurred_at="2026-07-30T00:00:00+00:00",
            cause="codex_event",
            component="codex_event_projector",
            thread_id="thread",
            turn_id="turn",
        )
        repeated, inserted_again = store.append_event(
            task_id=task.task_id,
            source_event_id="codex-event",
            event_type="turn.started",
            occurred_at="2026-07-30T00:00:00+00:00",
            cause="codex_event",
            component="codex_event_projector",
            thread_id="thread",
            turn_id="turn",
        )
        assert inserted is True
        assert inserted_again is False
        assert repeated == first
        assert [event.sequence for event in service.timeline(task.task_id)] == [1, 2]
    finally:
        store.close()
