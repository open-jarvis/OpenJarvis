"""Transactional SQLite persistence for canonical OpenJarvis tasks."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openjarvis.codex.redaction import redact_data
from openjarvis.codex.store import CodexStateStore
from openjarvis.tasks.types import (
    ExecutionLane,
    InvalidTaskTransition,
    TaskEvent,
    TaskOutcome,
    TaskRecord,
    TaskStatus,
    validate_outcome,
    validate_transition,
)

_TASK_SCHEMA_VERSION = 1

_TASK_SCHEMA = """\
CREATE TABLE IF NOT EXISTS schema_migrations (
    component       TEXT NOT NULL,
    version         INTEGER NOT NULL,
    name            TEXT NOT NULL,
    applied_at      TEXT NOT NULL,
    PRIMARY KEY (component, version)
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id             TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    correlation_id      TEXT NOT NULL UNIQUE,
    description         TEXT NOT NULL,
    status              TEXT NOT NULL,
    outcome             TEXT,
    execution_lane      TEXT NOT NULL,
    backend             TEXT NOT NULL,
    risk_level          INTEGER NOT NULL,
    result              TEXT NOT NULL DEFAULT '',
    error_category      TEXT,
    active_thread_id    TEXT,
    active_turn_id      TEXT,
    budget_warning      INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    version             INTEGER NOT NULL DEFAULT 1,
    last_event_sequence INTEGER NOT NULL DEFAULT 0,
    CHECK (risk_level BETWEEN 0 AND 4)
);

CREATE TABLE IF NOT EXISTS task_events (
    event_id        TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    sequence        INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    occurred_at     TEXT NOT NULL,
    cause           TEXT NOT NULL,
    component       TEXT NOT NULL,
    correlation_id  TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    status_from     TEXT,
    status_to       TEXT,
    thread_id       TEXT,
    turn_id         TEXT,
    item_id         TEXT,
    approval_id     TEXT,
    action_id       TEXT,
    artifact_id     TEXT,
    schema_version  TEXT NOT NULL,
    payload         TEXT NOT NULL,
    idempotency_key TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    UNIQUE (task_id, sequence),
    UNIQUE (task_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS task_steps (
    step_id          TEXT PRIMARY KEY,
    task_id          TEXT NOT NULL,
    step_index       INTEGER NOT NULL,
    name             TEXT NOT NULL,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    metadata         TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    UNIQUE (task_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_updated
    ON tasks(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_session_updated
    ON tasks(session_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_task_events_task_sequence
    ON task_events(task_id, sequence);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore(CodexStateStore):
    """Canonical task store that retains the Phase 2 Codex store contract."""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._migrate_task_schema()

    @property
    def schema_version(self) -> int:
        row = self._conn.execute(
            """
            SELECT MAX(version) FROM schema_migrations
            WHERE component='task_runtime'
            """
        ).fetchone()
        return int(row[0] or 0)

    def _migrate_task_schema(self) -> None:
        """Apply ordered and idempotent task-runtime migrations."""

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.executescript(_TASK_SCHEMA)
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations
                        (component, version, name, applied_at)
                    VALUES ('task_runtime', ?, 'canonical tasks and events', ?)
                    """,
                    (_TASK_SCHEMA_VERSION, _now()),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def create_task(
        self,
        *,
        task_id: str,
        session_id: str,
        correlation_id: str,
        description: str,
        execution_lane: ExecutionLane,
        backend: str,
        risk_level: int,
        component: str,
        cause: str,
        idempotency_key: str,
        occurred_at: str | None = None,
    ) -> tuple[TaskRecord, TaskEvent]:
        """Create a pending task and its first event in one transaction."""

        required = {
            "task_id": task_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "description": description,
            "component": component,
            "cause": cause,
            "idempotency_key": idempotency_key,
        }
        for field_name, value in required.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not 0 <= risk_level <= 4:
            raise ValueError("risk_level must be between 0 and 4")

        existing = self.get_task_by_correlation(correlation_id)
        if existing is not None:
            event = self.get_event_by_idempotency(existing.task_id, idempotency_key)
            if event is None:
                raise ValueError("correlation_id already belongs to another request")
            return existing, event

        timestamp = occurred_at or _now()
        event_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                duplicate = self._conn.execute(
                    """
                    SELECT task_id FROM task_events
                    WHERE task_id=? AND idempotency_key=?
                    """,
                    (task_id, idempotency_key),
                ).fetchone()
                if duplicate:
                    self._conn.rollback()
                    task = self.get_task(task_id)
                    event = self.get_event_by_idempotency(task_id, idempotency_key)
                    if task is None or event is None:
                        raise RuntimeError("idempotent task record is incomplete")
                    return task, event

                self._conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id, session_id, correlation_id, description,
                        status, execution_lane, backend, risk_level,
                        created_at, updated_at, version, last_event_sequence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                    """,
                    (
                        task_id,
                        session_id,
                        correlation_id,
                        description,
                        TaskStatus.PENDING.value,
                        execution_lane.value,
                        backend,
                        risk_level,
                        timestamp,
                        timestamp,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO task_events (
                        event_id, task_id, sequence, event_type, occurred_at,
                        cause, component, correlation_id, session_id,
                        status_to, schema_version, payload, idempotency_key
                    ) VALUES (?, ?, 1, 'task.created', ?, ?, ?, ?, ?, ?, '1.0', ?, ?)
                    """,
                    (
                        event_id,
                        task_id,
                        timestamp,
                        cause,
                        component,
                        correlation_id,
                        session_id,
                        TaskStatus.PENDING.value,
                        json.dumps({}, sort_keys=True),
                        idempotency_key,
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

        task = self.get_task(task_id)
        event = self.get_event(event_id)
        if task is None or event is None:
            raise RuntimeError("created task transaction could not be read back")
        return task, event

    def transition_task(
        self,
        task_id: str,
        *,
        requested: TaskStatus,
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
        occurred_at: str | None = None,
    ) -> tuple[TaskRecord, TaskEvent]:
        """Transition and append the state event in one short transaction."""

        for field_name, value in {
            "task_id": task_id,
            "component": component,
            "cause": cause,
            "idempotency_key": idempotency_key,
        }.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        validate_outcome(requested, outcome)

        existing_event = self.get_event_by_idempotency(task_id, idempotency_key)
        if existing_event is not None:
            if existing_event.status_to is not requested:
                raise InvalidTaskTransition(
                    "idempotency key was already used for another transition"
                )
            task = self.get_task(task_id)
            if task is None:
                raise KeyError(f"unknown task: {task_id}")
            return task, existing_event

        timestamp = occurred_at or _now()
        event_id = uuid.uuid4().hex
        safe_payload = redact_data(payload or {})
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown task: {task_id}")
                current = TaskStatus(row["status"])
                validate_transition(current, requested)
                sequence = int(row["last_event_sequence"]) + 1
                next_result = row["result"] if result is None else result
                next_error = (
                    row["error_category"]
                    if error_category is None
                    else error_category
                )
                next_thread = (
                    row["active_thread_id"]
                    if active_thread_id is None
                    else active_thread_id
                )
                next_turn = (
                    row["active_turn_id"]
                    if active_turn_id is None
                    else active_turn_id
                )
                next_warning = (
                    bool(row["budget_warning"])
                    if budget_warning is None
                    else budget_warning
                )
                self._conn.execute(
                    """
                    UPDATE tasks
                    SET status=?, outcome=?, result=?, error_category=?,
                        active_thread_id=?, active_turn_id=?, budget_warning=?,
                        updated_at=?, version=version+1,
                        last_event_sequence=?
                    WHERE task_id=?
                    """,
                    (
                        requested.value,
                        outcome.value if outcome else None,
                        next_result,
                        next_error,
                        next_thread,
                        next_turn,
                        int(next_warning),
                        timestamp,
                        sequence,
                        task_id,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO task_events (
                        event_id, task_id, sequence, event_type, occurred_at,
                        cause, component, correlation_id, session_id,
                        status_from, status_to, thread_id, turn_id,
                        schema_version, payload, idempotency_key
                    ) VALUES (?, ?, ?, 'task.state_changed', ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, '1.0', ?, ?)
                    """,
                    (
                        event_id,
                        task_id,
                        sequence,
                        timestamp,
                        cause,
                        component,
                        row["correlation_id"],
                        row["session_id"],
                        current.value,
                        requested.value,
                        next_thread,
                        next_turn,
                        json.dumps(safe_payload, sort_keys=True),
                        idempotency_key,
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

        task = self.get_task(task_id)
        event = self.get_event(event_id)
        if task is None or event is None:
            raise RuntimeError("transition transaction could not be read back")
        return task, event

    def get_task(self, task_id: str) -> TaskRecord | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        return self._task_from_row(row) if row else None

    def get_task_by_correlation(self, correlation_id: str) -> TaskRecord | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE correlation_id=?",
            (correlation_id,),
        ).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM tasks
                WHERE status=? ORDER BY updated_at DESC LIMIT ?
                """,
                (status.value, limit),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def list_recoverable_tasks(self) -> list[TaskRecord]:
        states = (
            TaskStatus.RUNNING.value,
            TaskStatus.WAITING_APPROVAL.value,
            TaskStatus.RECOVERING.value,
        )
        rows = self._conn.execute(
            """
            SELECT * FROM tasks WHERE status IN (?, ?, ?)
            ORDER BY updated_at
            """,
            states,
        ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get_event(self, event_id: str) -> TaskEvent | None:
        row = self._conn.execute(
            "SELECT * FROM task_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        return self._event_from_task_row(row) if row else None

    def get_event_by_idempotency(
        self,
        task_id: str,
        idempotency_key: str,
    ) -> TaskEvent | None:
        row = self._conn.execute(
            """
            SELECT * FROM task_events
            WHERE task_id=? AND idempotency_key=?
            """,
            (task_id, idempotency_key),
        ).fetchone()
        return self._event_from_task_row(row) if row else None

    def list_task_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[TaskEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = self._conn.execute(
            """
            SELECT * FROM task_events
            WHERE task_id=? AND sequence>?
            ORDER BY sequence LIMIT ?
            """,
            (task_id, after_sequence, limit),
        ).fetchall()
        return [self._event_from_task_row(row) for row in rows]

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            session_id=row["session_id"],
            correlation_id=row["correlation_id"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            outcome=TaskOutcome(row["outcome"]) if row["outcome"] else None,
            execution_lane=ExecutionLane(row["execution_lane"]),
            backend=row["backend"],
            risk_level=int(row["risk_level"]),
            result=row["result"] or "",
            error_category=row["error_category"],
            active_thread_id=row["active_thread_id"],
            active_turn_id=row["active_turn_id"],
            budget_warning=bool(row["budget_warning"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version=int(row["version"]),
        )

    @staticmethod
    def _event_from_task_row(row: sqlite3.Row) -> TaskEvent:
        return TaskEvent(
            event_id=row["event_id"],
            task_id=row["task_id"],
            sequence=int(row["sequence"]),
            event_type=row["event_type"],
            occurred_at=row["occurred_at"],
            cause=row["cause"],
            component=row["component"],
            correlation_id=row["correlation_id"],
            session_id=row["session_id"],
            status_from=TaskStatus(row["status_from"]) if row["status_from"] else None,
            status_to=TaskStatus(row["status_to"]) if row["status_to"] else None,
            thread_id=row["thread_id"],
            turn_id=row["turn_id"],
            item_id=row["item_id"],
            approval_id=row["approval_id"],
            action_id=row["action_id"],
            artifact_id=row["artifact_id"],
            schema_version=row["schema_version"],
            payload=json.loads(row["payload"]),
        )


__all__ = ["TaskStore"]
