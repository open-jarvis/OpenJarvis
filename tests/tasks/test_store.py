from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.tasks import (
    ExecutionLane,
    InvalidTaskTransition,
    TaskOutcome,
    TaskService,
    TaskStatus,
    TaskStore,
)


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    result = TaskStore(tmp_path / "runtime.db")
    yield result
    result.close()


def _create(service: TaskService, *, correlation_id: str = "corr-create"):
    return service.create(
        task_id="task-1",
        session_id="session-1",
        correlation_id=correlation_id,
        description="Read the isolated workspace",
        execution_lane=ExecutionLane.MODEL,
        backend="codex",
        risk_level=0,
        component="test",
        cause="user_request",
        idempotency_key="create-1",
    )


def test_store_enables_wal_foreign_keys_and_schema_version(store: TaskStore) -> None:
    assert store.journal_mode == "wal"
    assert store.foreign_keys_enabled is True
    assert store.schema_version == 4


def test_create_and_transition_are_atomic_and_ordered(store: TaskStore) -> None:
    service = TaskService(store)
    created = _create(service)
    running = service.transition(
        created.task_id,
        TaskStatus.RUNNING,
        component="task_orchestrator",
        cause="backend_selected",
        idempotency_key="run-1",
        active_thread_id="thread-1",
        active_turn_id="turn-1",
    )
    done = service.transition(
        running.task_id,
        TaskStatus.DONE,
        component="task_orchestrator",
        cause="terminal_safety_checks_passed",
        idempotency_key="done-1",
        outcome=TaskOutcome.COMPLETED,
        result="complete",
    )

    assert created.status is TaskStatus.PENDING
    assert running.status is TaskStatus.RUNNING
    assert done.status is TaskStatus.DONE
    assert done.outcome is TaskOutcome.COMPLETED
    assert done.version == 3
    events = service.timeline(done.task_id)
    assert [event.sequence for event in events] == [1, 2, 3]
    assert events[1].status_from is TaskStatus.PENDING
    assert events[1].status_to is TaskStatus.RUNNING
    assert events[1].component == "task_orchestrator"
    assert events[1].cause == "backend_selected"


def test_repeated_transition_key_is_idempotent(store: TaskStore) -> None:
    service = TaskService(store)
    task = _create(service)
    first = service.transition(
        task.task_id,
        TaskStatus.RUNNING,
        component="test",
        cause="start",
        idempotency_key="same-transition",
    )
    repeated = service.transition(
        task.task_id,
        TaskStatus.RUNNING,
        component="test",
        cause="start",
        idempotency_key="same-transition",
    )

    assert repeated == first
    assert len(service.timeline(task.task_id)) == 2


def test_reused_key_cannot_request_a_different_transition(store: TaskStore) -> None:
    service = TaskService(store)
    task = _create(service)
    service.transition(
        task.task_id,
        TaskStatus.RUNNING,
        component="test",
        cause="start",
        idempotency_key="one-key",
    )
    with pytest.raises(InvalidTaskTransition):
        service.transition(
            task.task_id,
            TaskStatus.PAUSED,
            component="test",
            cause="pause",
            idempotency_key="one-key",
        )


def test_invalid_transition_rolls_back_without_event(store: TaskStore) -> None:
    service = TaskService(store)
    task = _create(service)
    with pytest.raises(InvalidTaskTransition):
        service.transition(
            task.task_id,
            TaskStatus.DONE,
            component="test",
            cause="unsafe_shortcut",
            idempotency_key="bad-done",
            outcome=TaskOutcome.COMPLETED,
        )

    persisted = service.get(task.task_id)
    assert persisted is not None
    assert persisted.status is TaskStatus.PENDING
    assert persisted.version == 1
    assert len(service.timeline(task.task_id)) == 1


def test_correlation_create_is_idempotent_but_not_ambiguous(store: TaskStore) -> None:
    service = TaskService(store)
    first = _create(service)
    repeated = _create(service)
    assert repeated == first

    with pytest.raises(ValueError):
        service.create(
            task_id="task-other",
            session_id="session-1",
            correlation_id="corr-create",
            description="different request",
            component="test",
            cause="user_request",
            idempotency_key="different-create-key",
        )


def test_committed_event_is_projected_to_event_bus(store: TaskStore) -> None:
    bus = EventBus(record_history=True)
    service = TaskService(store, bus=bus)
    task = _create(service)

    assert len(bus.history) == 1
    assert bus.history[0].event_type is EventType.TASK_EVENT
    assert bus.history[0].data["task_id"] == task.task_id
    assert bus.history[0].data["sequence"] == 1


def test_foreign_key_prevents_orphan_event(store: TaskStore) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with store._conn:
            store._conn.execute(
                """
                INSERT INTO task_events (
                    event_id, task_id, sequence, event_type, occurred_at,
                    cause, component, correlation_id, session_id,
                    schema_version, payload
                ) VALUES ('orphan', 'missing', 1, 'test', 'now', 'test',
                          'test', 'corr', 'session', '1.0', '{}')
                """
            )
