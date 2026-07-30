"""Central authority for canonical task lifecycle changes."""

from __future__ import annotations

import uuid
from typing import Any

from openjarvis.core.events import EventBus, EventType
from openjarvis.tasks.identity import TaskIdentity
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import (
    ExecutionLane,
    TaskEvent,
    TaskOutcome,
    TaskRecord,
    TaskStatus,
)


class TaskService:
    """Create and transition tasks, then project committed events."""

    def __init__(self, store: TaskStore, *, bus: EventBus | None = None) -> None:
        self._store = store
        self._bus = bus

    @property
    def store(self) -> TaskStore:
        return self._store

    def create(
        self,
        *,
        session_id: str,
        correlation_id: str,
        description: str,
        execution_lane: ExecutionLane = ExecutionLane.MODEL,
        backend: str = "codex",
        risk_level: int = 0,
        component: str,
        cause: str,
        idempotency_key: str,
        task_id: str | None = None,
    ) -> TaskRecord:
        task, event = self._store.create_task(
            task_id=task_id or uuid.uuid4().hex,
            session_id=session_id,
            correlation_id=correlation_id,
            description=description,
            execution_lane=execution_lane,
            backend=backend,
            risk_level=risk_level,
            component=component,
            cause=cause,
            idempotency_key=idempotency_key,
        )
        self._project(event)
        return task

    def transition(
        self,
        task_id: str,
        requested: TaskStatus,
        *,
        component: str,
        cause: str,
        idempotency_key: str,
        outcome: TaskOutcome | None = None,
        result: str | None = None,
        error_category: str | None = None,
        active_thread_id: str | None = None,
        active_turn_id: str | None = None,
        budget_warning: bool | None = None,
        payload: dict[str, Any] | None = None,
    ) -> TaskRecord:
        task, event = self._store.transition_task(
            task_id,
            requested=requested,
            component=component,
            cause=cause,
            idempotency_key=idempotency_key,
            outcome=outcome,
            result=result,
            error_category=error_category,
            active_thread_id=active_thread_id,
            active_turn_id=active_turn_id,
            budget_warning=budget_warning,
            payload=payload,
        )
        self._project(event)
        return task

    def get(self, task_id: str) -> TaskRecord | None:
        return self._store.get_task(task_id)

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        return self._store.list_tasks(status=status, limit=limit)

    def timeline(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[TaskEvent]:
        return self._store.list_task_events(
            task_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def identity(self, task_id: str) -> TaskIdentity:
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        return TaskIdentity(
            task_id=task.task_id,
            session_id=task.session_id,
            correlation_id=task.correlation_id,
            thread_id=task.active_thread_id,
            turn_id=task.active_turn_id,
        ).validated()

    def project_committed(self, event: TaskEvent) -> None:
        """Publish one already-committed event without creating another write."""

        self._project(event)

    def _project(self, event: TaskEvent) -> None:
        if self._bus is None:
            return
        self._bus.publish(
            EventType.TASK_EVENT,
            {
                "event_id": event.event_id,
                "task_id": event.task_id,
                "session_id": event.session_id,
                "correlation_id": event.correlation_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "cause": event.cause,
                "component": event.component,
                "status_from": (
                    event.status_from.value if event.status_from is not None else None
                ),
                "status_to": (
                    event.status_to.value if event.status_to is not None else None
                ),
                "thread_id": event.thread_id,
                "turn_id": event.turn_id,
                "item_id": event.item_id,
                "approval_id": event.approval_id,
                "action_id": event.action_id,
                "artifact_id": event.artifact_id,
                "schema_version": event.schema_version,
                "payload": dict(event.payload),
            },
        )


__all__ = ["TaskService"]
