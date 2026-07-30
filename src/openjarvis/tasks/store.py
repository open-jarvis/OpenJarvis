"""Transactional SQLite persistence for canonical OpenJarvis tasks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openjarvis.codex.redaction import redact_data
from openjarvis.codex.store import CodexStateStore
from openjarvis.tasks.types import (
    ApprovalKind,
    ApprovalRecord,
    ApprovalStatus,
    ExecutionLane,
    InvalidTaskTransition,
    TaskArtifact,
    TaskEvent,
    TaskItem,
    TaskOutcome,
    TaskRecord,
    TaskSource,
    TaskStatus,
    TaskUsage,
    validate_outcome,
    validate_transition,
)

_TASK_SCHEMA_VERSION = 5

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

_IDENTITY_SCHEMA = """\
CREATE TABLE IF NOT EXISTS task_sources (
    source_id       TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    source_kind     TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    UNIQUE (source_kind, external_id)
);

CREATE TABLE IF NOT EXISTS task_event_sources (
    task_id         TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    event_id        TEXT NOT NULL UNIQUE,
    PRIMARY KEY (task_id, source_event_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (event_id) REFERENCES task_events(event_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS codex_items (
    item_id         TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    thread_id       TEXT NOT NULL,
    turn_id         TEXT NOT NULL,
    item_type       TEXT NOT NULL,
    status          TEXT NOT NULL,
    sequence        INTEGER NOT NULL,
    source_event_id TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    UNIQUE (turn_id, sequence),
    UNIQUE (turn_id, source_event_id)
);

CREATE INDEX IF NOT EXISTS idx_task_sources_task
    ON task_sources(task_id, source_kind);
CREATE INDEX IF NOT EXISTS idx_codex_items_task_turn
    ON codex_items(task_id, turn_id, sequence);
"""

_ARTIFACT_SCHEMA = """\
CREATE TABLE IF NOT EXISTS task_artifacts (
    artifact_id     TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    kind            TEXT NOT NULL,
    media_type      TEXT NOT NULL,
    byte_size       INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    storage_ref     TEXT NOT NULL,
    content         BLOB NOT NULL,
    created_at      TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_artifacts_task
    ON task_artifacts(task_id, created_at);
"""

_APPROVAL_SCHEMA = """\
CREATE TABLE IF NOT EXISTS task_approvals (
    approval_id     TEXT PRIMARY KEY,
    request_id      TEXT NOT NULL UNIQUE,
    task_id         TEXT NOT NULL,
    thread_id       TEXT NOT NULL,
    turn_id         TEXT,
    item_id         TEXT,
    action_id       TEXT,
    kind            TEXT NOT NULL,
    action          TEXT NOT NULL,
    target          TEXT NOT NULL,
    effect          TEXT NOT NULL,
    risk_level      INTEGER NOT NULL,
    sandbox         TEXT NOT NULL,
    cwd             TEXT NOT NULL,
    undo            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    status          TEXT NOT NULL,
    user_decision   TEXT,
    decision_at     TEXT,
    decision_id     TEXT UNIQUE,
    response_id     TEXT UNIQUE,
    responded_at    TEXT,
    payload         TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    CHECK (risk_level BETWEEN 0 AND 4)
);

CREATE INDEX IF NOT EXISTS idx_task_approvals_pending
    ON task_approvals(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_task_approvals_task
    ON task_approvals(task_id, created_at);
"""

_USAGE_SCHEMA = """\
CREATE TABLE IF NOT EXISTS task_usage (
    task_id             TEXT NOT NULL,
    turn_id             TEXT NOT NULL,
    turn_input_tokens   INTEGER NOT NULL DEFAULT 0,
    turn_output_tokens  INTEGER NOT NULL DEFAULT 0,
    thread_input_tokens INTEGER NOT NULL DEFAULT 0,
    thread_output_tokens INTEGER NOT NULL DEFAULT 0,
    warning             INTEGER NOT NULL DEFAULT 0,
    hard_exceeded       INTEGER NOT NULL DEFAULT 0,
    reason              TEXT,
    source_event_id     TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (task_id, turn_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_usage_task
    ON task_usage(task_id, updated_at);
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
                    (1, _now()),
                )
                self._conn.executescript(_IDENTITY_SCHEMA)
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations
                        (component, version, name, applied_at)
                    VALUES ('task_runtime', ?, 'task identity sources and items', ?)
                    """,
                    (2, _now()),
                )
                self._conn.executescript(_ARTIFACT_SCHEMA)
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations
                        (component, version, name, applied_at)
                    VALUES ('task_runtime', 3, 'bounded task artifacts', ?)
                    """,
                    (_now(),),
                )
                self._conn.executescript(_USAGE_SCHEMA)
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations
                        (component, version, name, applied_at)
                    VALUES ('task_runtime', 5, 'separate turn and task usage', ?)
                    """,
                    (_now(),),
                )
                self._conn.executescript(_APPROVAL_SCHEMA)
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations
                        (component, version, name, applied_at)
                    VALUES ('task_runtime', 4, 'persistent exact-once approvals', ?)
                    """,
                    (_now(),),
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

    def add_source(
        self,
        task_id: str,
        *,
        source_kind: str,
        external_id: str,
        metadata: dict[str, Any] | None = None,
        source_id: str | None = None,
    ) -> TaskSource:
        """Attach one idempotent legacy/API source to a canonical task."""

        for field_name, value in {
            "task_id": task_id,
            "source_kind": source_kind,
            "external_id": external_id,
        }.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        safe_metadata = redact_data(metadata or {})
        actual_source_id = source_id or uuid.uuid4().hex
        timestamp = _now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO task_sources (
                    source_id, task_id, source_kind, external_id,
                    created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_kind, external_id) DO NOTHING
                """,
                (
                    actual_source_id,
                    task_id,
                    source_kind,
                    external_id,
                    timestamp,
                    json.dumps(safe_metadata, sort_keys=True),
                ),
            )
        row = self._conn.execute(
            """
            SELECT * FROM task_sources
            WHERE source_kind=? AND external_id=?
            """,
            (source_kind, external_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("task source could not be read back")
        if row["task_id"] != task_id:
            raise ValueError("source already belongs to another canonical task")
        return self._source_from_row(row)

    def list_sources(self, task_id: str) -> list[TaskSource]:
        rows = self._conn.execute(
            """
            SELECT * FROM task_sources
            WHERE task_id=? ORDER BY created_at, source_id
            """,
            (task_id,),
        ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def save_item(
        self,
        *,
        item_id: str,
        task_id: str,
        session_id: str,
        thread_id: str,
        turn_id: str,
        item_type: str,
        status: str,
        sequence: int,
        source_event_id: str,
        payload: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> TaskItem:
        """Insert or update one correlated Codex item idempotently."""

        for field_name, value in {
            "item_id": item_id,
            "task_id": task_id,
            "session_id": session_id,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "item_type": item_type,
            "status": status,
            "source_event_id": source_event_id,
        }.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if sequence <= 0:
            raise ValueError("sequence must be positive")
        timestamp = occurred_at or _now()
        safe_payload = redact_data(payload or {})
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO codex_items (
                    item_id, task_id, session_id, thread_id, turn_id,
                    item_type, status, sequence, source_event_id,
                    created_at, updated_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    item_id,
                    task_id,
                    session_id,
                    thread_id,
                    turn_id,
                    item_type,
                    status,
                    sequence,
                    source_event_id,
                    timestamp,
                    timestamp,
                    json.dumps(safe_payload, sort_keys=True),
                ),
            )
        row = self._conn.execute(
            "SELECT * FROM codex_items WHERE item_id=?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Codex item could not be read back")
        return self._item_from_row(row)

    def list_items(
        self,
        task_id: str,
        *,
        turn_id: str | None = None,
    ) -> list[TaskItem]:
        if turn_id is None:
            rows = self._conn.execute(
                """
                SELECT * FROM codex_items
                WHERE task_id=? ORDER BY turn_id, sequence
                """,
                (task_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM codex_items
                WHERE task_id=? AND turn_id=? ORDER BY sequence
                """,
                (task_id, turn_id),
            ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def save_artifact(
        self,
        *,
        task_id: str,
        kind: str,
        media_type: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
        artifact_id: str | None = None,
    ) -> TaskArtifact:
        """Persist a redacted bounded payload and return its immutable record."""

        for field_name, value in {
            "task_id": task_id,
            "kind": kind,
            "media_type": media_type,
        }.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not isinstance(content, bytes):
            raise TypeError("artifact content must be bytes")
        actual_id = artifact_id or uuid.uuid4().hex
        digest = hashlib.sha256(content).hexdigest()
        timestamp = _now()
        storage_ref = f"sqlite:task_artifacts/{actual_id}"
        safe_metadata = redact_data(metadata or {})
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO task_artifacts (
                    artifact_id, task_id, kind, media_type, byte_size,
                    sha256, storage_ref, content, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO NOTHING
                """,
                (
                    actual_id,
                    task_id,
                    kind,
                    media_type,
                    len(content),
                    digest,
                    storage_ref,
                    content,
                    timestamp,
                    json.dumps(safe_metadata, sort_keys=True),
                ),
            )
        row = self._conn.execute(
            "SELECT * FROM task_artifacts WHERE artifact_id=?",
            (actual_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("task artifact could not be read back")
        record = self._artifact_from_row(row)
        if record.task_id != task_id or record.sha256 != digest:
            raise ValueError("artifact_id already belongs to different content")
        return record

    def get_artifact(self, artifact_id: str) -> TaskArtifact | None:
        row = self._conn.execute(
            "SELECT * FROM task_artifacts WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
        return self._artifact_from_row(row) if row else None

    def read_artifact(self, artifact_id: str) -> bytes:
        row = self._conn.execute(
            "SELECT content FROM task_artifacts WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown artifact: {artifact_id}")
        return bytes(row["content"])

    def list_artifacts(self, task_id: str) -> list[TaskArtifact]:
        rows = self._conn.execute(
            """
            SELECT * FROM task_artifacts
            WHERE task_id=? ORDER BY created_at, artifact_id
            """,
            (task_id,),
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def queue_approval(
        self,
        *,
        request_id: str,
        task_id: str,
        thread_id: str,
        turn_id: str | None,
        item_id: str | None,
        action_id: str | None,
        kind: ApprovalKind,
        action: str,
        target: str,
        effect: str,
        risk_level: int,
        sandbox: str,
        cwd: str,
        undo: str,
        payload: dict[str, Any] | None = None,
        ttl_seconds: float = 300.0,
        approval_id: str | None = None,
    ) -> ApprovalRecord:
        """Persist one approval request before any component waits for it."""

        for field_name, value in {
            "request_id": request_id,
            "task_id": task_id,
            "thread_id": thread_id,
            "action": action,
            "effect": effect,
            "sandbox": sandbox,
            "cwd": cwd,
        }.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not 0 <= risk_level <= 4:
            raise ValueError("risk_level must be between 0 and 4")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        existing = self.get_approval_by_request(request_id)
        if existing is not None:
            if (
                existing.task_id != task_id
                or existing.thread_id != thread_id
                or existing.kind is not kind
            ):
                raise ValueError("approval request_id belongs to another action")
            return existing

        now = datetime.now(timezone.utc)
        actual_id = approval_id or uuid.uuid4().hex
        safe_payload = redact_data(payload or {})
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO task_approvals (
                    approval_id, request_id, task_id, thread_id, turn_id,
                    item_id, action_id, kind, action, target, effect,
                    risk_level, sandbox, cwd, undo, created_at, expires_at,
                    status, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?)
                ON CONFLICT(request_id) DO NOTHING
                """,
                (
                    actual_id,
                    request_id,
                    task_id,
                    thread_id,
                    turn_id,
                    item_id,
                    action_id,
                    kind.value,
                    action,
                    target,
                    effect,
                    risk_level,
                    sandbox,
                    cwd,
                    undo,
                    now.isoformat(),
                    (now + timedelta(seconds=ttl_seconds)).isoformat(),
                    ApprovalStatus.PENDING.value,
                    json.dumps(safe_payload, sort_keys=True),
                ),
            )
        record = self.get_approval_by_request(request_id)
        if record is None:
            raise RuntimeError("approval request could not be read back")
        return record

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        row = self._conn.execute(
            "SELECT * FROM task_approvals WHERE approval_id=?",
            (approval_id,),
        ).fetchone()
        return self._approval_from_row(row) if row else None

    def get_approval_by_request(self, request_id: str) -> ApprovalRecord | None:
        row = self._conn.execute(
            "SELECT * FROM task_approvals WHERE request_id=?",
            (request_id,),
        ).fetchone()
        return self._approval_from_row(row) if row else None

    def list_pending_approvals(
        self,
        *,
        task_id: str | None = None,
    ) -> list[ApprovalRecord]:
        if task_id is None:
            rows = self._conn.execute(
                """
                SELECT * FROM task_approvals
                WHERE status=? ORDER BY created_at
                """,
                (ApprovalStatus.PENDING.value,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM task_approvals
                WHERE status=? AND task_id=? ORDER BY created_at
                """,
                (ApprovalStatus.PENDING.value, task_id),
            ).fetchall()
        return [self._approval_from_row(row) for row in rows]

    def decide_approval(
        self,
        approval_id: str,
        *,
        allow: bool,
        decision_id: str,
        decided_at: str | None = None,
    ) -> ApprovalRecord:
        """Apply one exact user decision with compare-and-set semantics."""

        if not decision_id.strip():
            raise ValueError("decision_id must be non-empty")
        target_status = (
            ApprovalStatus.APPROVED if allow else ApprovalStatus.DENIED
        )
        user_decision = "allow" if allow else "deny"
        timestamp = decided_at or _now()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM task_approvals WHERE approval_id=?",
                    (approval_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown approval: {approval_id}")
                current = ApprovalStatus(row["status"])
                if current is ApprovalStatus.PENDING:
                    self._conn.execute(
                        """
                        UPDATE task_approvals
                        SET status=?, user_decision=?, decision_at=?,
                            decision_id=?
                        WHERE approval_id=? AND status=?
                        """,
                        (
                            target_status.value,
                            user_decision,
                            timestamp,
                            decision_id,
                            approval_id,
                            ApprovalStatus.PENDING.value,
                        ),
                    )
                elif row["user_decision"] != user_decision:
                    raise ValueError("approval already has a conflicting decision")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        record = self.get_approval(approval_id)
        if record is None:
            raise RuntimeError("approval decision could not be read back")
        return record

    def expire_approval(
        self,
        approval_id: str,
        *,
        decision_id: str,
    ) -> ApprovalRecord:
        """Deny one still-pending request after its bounded wait expires."""

        timestamp = _now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE task_approvals
                SET status=?, user_decision='deny', decision_at=?,
                    decision_id=?
                WHERE approval_id=? AND status=?
                """,
                (
                    ApprovalStatus.EXPIRED.value,
                    timestamp,
                    decision_id,
                    approval_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
        record = self.get_approval(approval_id)
        if record is None:
            raise KeyError(f"unknown approval: {approval_id}")
        return record

    def claim_approval_response(
        self,
        approval_id: str,
        *,
        response_id: str,
    ) -> ApprovalRecord:
        """Persist exactly one response identity for the App Server."""

        if not response_id.strip():
            raise ValueError("response_id must be non-empty")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM task_approvals WHERE approval_id=?",
                    (approval_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown approval: {approval_id}")
                if ApprovalStatus(row["status"]) is ApprovalStatus.PENDING:
                    raise ValueError("pending approval cannot produce a response")
                if row["response_id"] is None:
                    self._conn.execute(
                        """
                        UPDATE task_approvals
                        SET response_id=?, responded_at=?
                        WHERE approval_id=? AND response_id IS NULL
                        """,
                        (response_id, _now(), approval_id),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        record = self.get_approval(approval_id)
        if record is None:
            raise RuntimeError("approval response could not be read back")
        return record

    def save_usage(
        self,
        *,
        task_id: str,
        turn_id: str,
        turn_input_tokens: int,
        turn_output_tokens: int,
        thread_input_tokens: int,
        thread_output_tokens: int,
        warning: bool,
        hard_exceeded: bool,
        reason: str | None,
        source_event_id: str,
    ) -> TaskUsage:
        """Upsert the latest usage snapshot for a turn."""

        for field_name, value in {
            "task_id": task_id,
            "turn_id": turn_id,
            "source_event_id": source_event_id,
        }.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        values = (
            turn_input_tokens,
            turn_output_tokens,
            thread_input_tokens,
            thread_output_tokens,
        )
        if any(value < 0 for value in values):
            raise ValueError("token usage cannot be negative")
        timestamp = _now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO task_usage (
                    task_id, turn_id, turn_input_tokens, turn_output_tokens,
                    thread_input_tokens, thread_output_tokens, warning,
                    hard_exceeded, reason, source_event_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, turn_id) DO UPDATE SET
                    turn_input_tokens=MAX(
                        task_usage.turn_input_tokens,
                        excluded.turn_input_tokens
                    ),
                    turn_output_tokens=MAX(
                        task_usage.turn_output_tokens,
                        excluded.turn_output_tokens
                    ),
                    thread_input_tokens=MAX(
                        task_usage.thread_input_tokens,
                        excluded.thread_input_tokens
                    ),
                    thread_output_tokens=MAX(
                        task_usage.thread_output_tokens,
                        excluded.thread_output_tokens
                    ),
                    warning=MAX(task_usage.warning, excluded.warning),
                    hard_exceeded=MAX(
                        task_usage.hard_exceeded,
                        excluded.hard_exceeded
                    ),
                    reason=COALESCE(excluded.reason, task_usage.reason),
                    source_event_id=excluded.source_event_id,
                    updated_at=excluded.updated_at
                """,
                (
                    task_id,
                    turn_id,
                    *values,
                    int(warning),
                    int(hard_exceeded),
                    reason,
                    source_event_id,
                    timestamp,
                ),
            )
        record = self.get_usage(task_id, turn_id)
        if record is None:
            raise RuntimeError("usage snapshot could not be read back")
        return record

    def get_usage(self, task_id: str, turn_id: str) -> TaskUsage | None:
        row = self._conn.execute(
            "SELECT * FROM task_usage WHERE task_id=? AND turn_id=?",
            (task_id, turn_id),
        ).fetchone()
        return self._usage_from_row(row) if row else None

    def list_usage(self, task_id: str) -> list[TaskUsage]:
        rows = self._conn.execute(
            """
            SELECT * FROM task_usage
            WHERE task_id=? ORDER BY updated_at, turn_id
            """,
            (task_id,),
        ).fetchall()
        return [self._usage_from_row(row) for row in rows]

    def task_token_total(self, task_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(turn_input_tokens + turn_output_tokens), 0)
            FROM task_usage WHERE task_id=?
            """,
            (task_id,),
        ).fetchone()
        return int(row[0] or 0)

    def append_event(
        self,
        *,
        task_id: str,
        source_event_id: str,
        event_type: str,
        occurred_at: str,
        cause: str,
        component: str,
        thread_id: str | None = None,
        turn_id: str | None = None,
        item_id: str | None = None,
        approval_id: str | None = None,
        action_id: str | None = None,
        artifact_id: str | None = None,
        schema_version: str = "1.0",
        payload: dict[str, Any] | None = None,
    ) -> tuple[TaskEvent, bool]:
        """Append a non-state event once and preserve task-wide order."""

        for field_name, value in {
            "task_id": task_id,
            "source_event_id": source_event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "cause": cause,
            "component": component,
            "schema_version": schema_version,
        }.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")

        existing = self._event_by_source(task_id, source_event_id)
        if existing is not None:
            return existing, False

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
                duplicate = self._event_by_source(task_id, source_event_id)
                if duplicate is not None:
                    self._conn.rollback()
                    return duplicate, False
                sequence = int(row["last_event_sequence"]) + 1
                self._conn.execute(
                    """
                    UPDATE tasks
                    SET last_event_sequence=?, updated_at=?, version=version+1
                    WHERE task_id=?
                    """,
                    (sequence, occurred_at, task_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO task_events (
                        event_id, task_id, sequence, event_type, occurred_at,
                        cause, component, correlation_id, session_id,
                        thread_id, turn_id, item_id, approval_id, action_id,
                        artifact_id, schema_version, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        task_id,
                        sequence,
                        event_type,
                        occurred_at,
                        cause,
                        component,
                        row["correlation_id"],
                        row["session_id"],
                        thread_id,
                        turn_id,
                        item_id,
                        approval_id,
                        action_id,
                        artifact_id,
                        schema_version,
                        json.dumps(safe_payload, sort_keys=True),
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO task_event_sources
                        (task_id, source_event_id, event_id)
                    VALUES (?, ?, ?)
                    """,
                    (task_id, source_event_id, event_id),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        event = self.get_event(event_id)
        if event is None:
            raise RuntimeError("task event could not be read back")
        return event, True

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

    def _event_by_source(
        self,
        task_id: str,
        source_event_id: str,
    ) -> TaskEvent | None:
        row = self._conn.execute(
            """
            SELECT e.* FROM task_event_sources s
            JOIN task_events e ON e.event_id=s.event_id
            WHERE s.task_id=? AND s.source_event_id=?
            """,
            (task_id, source_event_id),
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

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> TaskSource:
        return TaskSource(
            source_id=row["source_id"],
            task_id=row["task_id"],
            source_kind=row["source_kind"],
            external_id=row["external_id"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> TaskItem:
        return TaskItem(
            item_id=row["item_id"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            thread_id=row["thread_id"],
            turn_id=row["turn_id"],
            item_type=row["item_type"],
            status=row["status"],
            sequence=int(row["sequence"]),
            source_event_id=row["source_event_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            payload=json.loads(row["payload"]),
        )

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> TaskArtifact:
        return TaskArtifact(
            artifact_id=row["artifact_id"],
            task_id=row["task_id"],
            kind=row["kind"],
            media_type=row["media_type"],
            byte_size=int(row["byte_size"]),
            sha256=row["sha256"],
            storage_ref=row["storage_ref"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row["approval_id"],
            request_id=row["request_id"],
            task_id=row["task_id"],
            thread_id=row["thread_id"],
            turn_id=row["turn_id"],
            item_id=row["item_id"],
            action_id=row["action_id"],
            kind=ApprovalKind(row["kind"]),
            action=row["action"],
            target=row["target"],
            effect=row["effect"],
            risk_level=int(row["risk_level"]),
            sandbox=row["sandbox"],
            cwd=row["cwd"],
            undo=row["undo"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            status=ApprovalStatus(row["status"]),
            user_decision=row["user_decision"],
            decision_at=row["decision_at"],
            decision_id=row["decision_id"],
            response_id=row["response_id"],
            responded_at=row["responded_at"],
            payload=json.loads(row["payload"]),
        )

    @staticmethod
    def _usage_from_row(row: sqlite3.Row) -> TaskUsage:
        return TaskUsage(
            task_id=row["task_id"],
            turn_id=row["turn_id"],
            turn_input_tokens=int(row["turn_input_tokens"]),
            turn_output_tokens=int(row["turn_output_tokens"]),
            thread_input_tokens=int(row["thread_input_tokens"]),
            thread_output_tokens=int(row["thread_output_tokens"]),
            warning=bool(row["warning"]),
            hard_exceeded=bool(row["hard_exceeded"]),
            reason=row["reason"],
            source_event_id=row["source_event_id"],
            updated_at=row["updated_at"],
        )


__all__ = ["TaskStore"]
