"""Minimal SQLite persistence for Codex thread and turn references."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openjarvis.codex.redaction import redact_data
from openjarvis.codex.types import (
    ApprovalMode,
    CodexBackendKind,
    CodexEvent,
    SandboxMode,
)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS codex_threads (
    task_id                 TEXT NOT NULL,
    session_id              TEXT NOT NULL,
    correlation_id          TEXT NOT NULL UNIQUE,
    thread_id               TEXT NOT NULL UNIQUE,
    backend                 TEXT NOT NULL,
    sandbox                 TEXT NOT NULL,
    approval_mode           TEXT NOT NULL,
    cwd                     TEXT NOT NULL,
    model_config            TEXT NOT NULL,
    status                  TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    last_event_sequence     INTEGER NOT NULL DEFAULT 0,
    resume_checkpoint       TEXT,
    PRIMARY KEY (task_id, session_id)
);

CREATE TABLE IF NOT EXISTS codex_turns (
    turn_id                 TEXT PRIMARY KEY,
    task_id                 TEXT NOT NULL,
    session_id              TEXT NOT NULL,
    correlation_id          TEXT NOT NULL UNIQUE,
    thread_id               TEXT NOT NULL,
    backend                 TEXT NOT NULL,
    sandbox                 TEXT NOT NULL,
    approval_mode           TEXT NOT NULL,
    cwd                     TEXT NOT NULL,
    runtime_evidence        TEXT NOT NULL DEFAULT '{}',
    status                  TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    FOREIGN KEY (task_id, session_id)
        REFERENCES codex_threads(task_id, session_id) ON DELETE CASCADE,
    FOREIGN KEY (thread_id)
        REFERENCES codex_threads(thread_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS codex_events (
    event_id                TEXT PRIMARY KEY,
    sequence                INTEGER NOT NULL,
    occurred_at             TEXT NOT NULL,
    task_id                 TEXT NOT NULL,
    session_id              TEXT NOT NULL,
    thread_id               TEXT NOT NULL,
    turn_id                 TEXT,
    item_id                 TEXT,
    backend                 TEXT NOT NULL,
    event_type              TEXT NOT NULL,
    schema_version          TEXT NOT NULL,
    payload                 TEXT NOT NULL,
    UNIQUE (thread_id, sequence),
    FOREIGN KEY (task_id, session_id)
        REFERENCES codex_threads(task_id, session_id) ON DELETE CASCADE,
    FOREIGN KEY (thread_id)
        REFERENCES codex_threads(thread_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_codex_threads_updated
    ON codex_threads(updated_at);
CREATE INDEX IF NOT EXISTS idx_codex_turns_thread
    ON codex_turns(thread_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_codex_events_thread
    ON codex_events(thread_id, sequence);
"""


@dataclass(frozen=True, slots=True)
class CodexThreadRecord:
    """Persisted OpenJarvis-to-Codex thread mapping."""

    task_id: str
    session_id: str
    correlation_id: str
    thread_id: str
    backend: CodexBackendKind
    sandbox: SandboxMode
    approval_mode: ApprovalMode
    cwd: str
    model_config: dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    last_event_sequence: int = 0
    resume_checkpoint: str | None = None


@dataclass(frozen=True, slots=True)
class CodexTurnRecord:
    """Persisted turn reference."""

    turn_id: str
    task_id: str
    session_id: str
    correlation_id: str
    thread_id: str
    backend: CodexBackendKind
    sandbox: SandboxMode
    approval_mode: ApprovalMode
    cwd: str
    status: str
    created_at: str
    updated_at: str
    runtime_evidence: dict[str, Any] = field(default_factory=dict)


def with_confirmed_model_evidence(
    model_config: dict[str, Any],
    *,
    actual_model: str | None,
    actual_effort: str | None,
    source: str,
) -> dict[str, Any]:
    """Attach confirmed protocol values to a requested thread config."""

    result = dict(model_config)
    if actual_model is not None:
        result["actual_model"] = actual_model
    if actual_effort is not None:
        result["actual_effort"] = actual_effort
    if actual_model is not None or actual_effort is not None:
        result["evidence_source"] = source
    return result


def resolve_turn_model_evidence(
    thread: CodexThreadRecord,
    *,
    requested_model: str | None,
    requested_effort: str | None,
) -> tuple[str | None, str | None, str]:
    """Resolve a turn only when its override matches confirmed thread values."""

    model = thread.model_config.get("actual_model")
    effort = thread.model_config.get("actual_effort")
    actual_model = model if requested_model in (None, model) else None
    actual_effort = effort if requested_effort in (None, effort) else None
    source = (
        str(thread.model_config.get("evidence_source") or "unknown")
        if actual_model or actual_effort
        else "unknown"
    )
    return (
        str(actual_model) if actual_model else None,
        str(actual_effort) if actual_effort else None,
        source,
    )


class CodexStateStore:
    """Small WAL-backed store; not a replacement for the Phase 3 task store."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            from openjarvis.security.file_utils import secure_create

            secure_create(Path(self._db_path))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._ensure_turn_evidence_columns()
        self._conn.commit()

    def _ensure_turn_evidence_columns(self) -> None:
        """Upgrade existing Phase 2 databases without rewriting turn data."""

        existing = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(codex_turns)")
        }
        if "runtime_evidence" not in existing:
            self._conn.execute(
                "ALTER TABLE codex_turns ADD COLUMN "
                "runtime_evidence TEXT NOT NULL DEFAULT '{}'"
            )

    @property
    def journal_mode(self) -> str:
        row = self._conn.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]).lower()

    @property
    def foreign_keys_enabled(self) -> bool:
        row = self._conn.execute("PRAGMA foreign_keys").fetchone()
        return bool(row[0])

    def save_thread(self, record: CodexThreadRecord) -> CodexThreadRecord:
        """Insert a mapping or idempotently return its correlation match."""

        existing = self.get_thread_by_correlation(record.correlation_id)
        if existing is not None:
            return existing
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO codex_threads (
                    task_id, session_id, correlation_id, thread_id, backend,
                    sandbox, approval_mode, cwd, model_config, status,
                    created_at, updated_at, last_event_sequence, resume_checkpoint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, session_id) DO UPDATE SET
                    correlation_id=excluded.correlation_id,
                    thread_id=excluded.thread_id,
                    backend=excluded.backend,
                    sandbox=excluded.sandbox,
                    approval_mode=excluded.approval_mode,
                    cwd=excluded.cwd,
                    model_config=excluded.model_config,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    resume_checkpoint=excluded.resume_checkpoint
                """,
                (
                    record.task_id,
                    record.session_id,
                    record.correlation_id,
                    record.thread_id,
                    record.backend.value,
                    record.sandbox.value,
                    record.approval_mode.value,
                    record.cwd,
                    json.dumps(redact_data(record.model_config), sort_keys=True),
                    record.status,
                    record.created_at,
                    record.updated_at,
                    record.last_event_sequence,
                    record.resume_checkpoint,
                ),
            )
        return self.get_thread(record.task_id, record.session_id) or record

    def get_thread(
        self,
        task_id: str,
        session_id: str,
    ) -> CodexThreadRecord | None:
        row = self._conn.execute(
            "SELECT * FROM codex_threads WHERE task_id=? AND session_id=?",
            (task_id, session_id),
        ).fetchone()
        return self._thread_from_row(row) if row else None

    def get_thread_by_id(self, thread_id: str) -> CodexThreadRecord | None:
        row = self._conn.execute(
            "SELECT * FROM codex_threads WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        return self._thread_from_row(row) if row else None

    def get_thread_by_correlation(
        self,
        correlation_id: str,
    ) -> CodexThreadRecord | None:
        row = self._conn.execute(
            "SELECT * FROM codex_threads WHERE correlation_id=?",
            (correlation_id,),
        ).fetchone()
        return self._thread_from_row(row) if row else None

    def list_threads(self, *, limit: int = 100) -> list[CodexThreadRecord]:
        rows = self._conn.execute(
            "SELECT * FROM codex_threads ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._thread_from_row(row) for row in rows]

    def update_thread(
        self,
        thread_id: str,
        *,
        status: str,
        updated_at: str,
        resume_checkpoint: str | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE codex_threads
                SET status=?, updated_at=?, resume_checkpoint=?
                WHERE thread_id=?
                """,
                (status, updated_at, resume_checkpoint, thread_id),
            )

    def update_thread_model_evidence(
        self,
        thread_id: str,
        *,
        actual_model: str | None,
        actual_effort: str | None,
        evidence_source: str,
    ) -> None:
        """Merge confirmed protocol metadata into the thread JSON record."""

        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT model_config FROM codex_threads WHERE thread_id=?",
                (thread_id,),
            ).fetchone()
            if row is None:
                return
            model_config = json.loads(row["model_config"])
            model_config.pop("actual_model", None)
            model_config.pop("actual_effort", None)
            model_config.pop("evidence_source", None)
            if actual_model is not None:
                model_config["actual_model"] = actual_model
            if actual_effort is not None:
                model_config["actual_effort"] = actual_effort
            if actual_model is not None or actual_effort is not None:
                model_config["evidence_source"] = evidence_source
            self._conn.execute(
                "UPDATE codex_threads SET model_config=? WHERE thread_id=?",
                (
                    json.dumps(redact_data(model_config), sort_keys=True),
                    thread_id,
                ),
            )

    def next_sequence(self, thread_id: str) -> int:
        """Atomically allocate the next per-thread event sequence."""

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT last_event_sequence FROM codex_threads WHERE thread_id=?",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown Codex thread: {thread_id}")
                sequence = int(row[0]) + 1
                self._conn.execute(
                    """
                    UPDATE codex_threads
                    SET last_event_sequence=?
                    WHERE thread_id=?
                    """,
                    (sequence, thread_id),
                )
                self._conn.commit()
                return sequence
            except Exception:
                self._conn.rollback()
                raise

    def save_turn(self, record: CodexTurnRecord) -> CodexTurnRecord:
        existing = self.get_turn_by_correlation(record.correlation_id)
        if existing is not None:
            return existing
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO codex_turns (
                    turn_id, task_id, session_id, correlation_id, thread_id,
                    backend, sandbox, approval_mode, cwd, runtime_evidence,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.turn_id,
                    record.task_id,
                    record.session_id,
                    record.correlation_id,
                    record.thread_id,
                    record.backend.value,
                    record.sandbox.value,
                    record.approval_mode.value,
                    record.cwd,
                    json.dumps(
                        redact_data(record.runtime_evidence),
                        sort_keys=True,
                    ),
                    record.status,
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get_turn(self, turn_id: str) -> CodexTurnRecord | None:
        row = self._conn.execute(
            "SELECT * FROM codex_turns WHERE turn_id=?",
            (turn_id,),
        ).fetchone()
        return self._turn_from_row(row) if row else None

    def get_turn_by_correlation(
        self,
        correlation_id: str,
    ) -> CodexTurnRecord | None:
        row = self._conn.execute(
            "SELECT * FROM codex_turns WHERE correlation_id=?",
            (correlation_id,),
        ).fetchone()
        return self._turn_from_row(row) if row else None

    def update_turn(self, turn_id: str, *, status: str, updated_at: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE codex_turns SET status=?, updated_at=? WHERE turn_id=?",
                (status, updated_at, turn_id),
            )

    def save_event(self, event: CodexEvent) -> bool:
        """Persist one redacted event, returning false for a duplicate."""

        try:
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    INSERT INTO codex_events (
                        event_id, sequence, occurred_at, task_id, session_id,
                        thread_id, turn_id, item_id, backend, event_type,
                        schema_version, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.sequence,
                        event.occurred_at,
                        event.task_id,
                        event.session_id,
                        event.thread_id,
                        event.turn_id,
                        event.item_id,
                        event.backend.value,
                        event.event_type.value,
                        event.schema_version,
                        json.dumps(redact_data(event.payload), sort_keys=True),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def has_event(self, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM codex_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        return row is not None

    def list_events(self, thread_id: str) -> list[CodexEvent]:
        rows = self._conn.execute(
            "SELECT * FROM codex_events WHERE thread_id=? ORDER BY sequence",
            (thread_id,),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _thread_from_row(row: sqlite3.Row) -> CodexThreadRecord:
        return CodexThreadRecord(
            task_id=row["task_id"],
            session_id=row["session_id"],
            correlation_id=row["correlation_id"],
            thread_id=row["thread_id"],
            backend=CodexBackendKind(row["backend"]),
            sandbox=SandboxMode(row["sandbox"]),
            approval_mode=ApprovalMode(row["approval_mode"]),
            cwd=row["cwd"],
            model_config=json.loads(row["model_config"]),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_event_sequence=row["last_event_sequence"],
            resume_checkpoint=row["resume_checkpoint"],
        )

    @staticmethod
    def _turn_from_row(row: sqlite3.Row) -> CodexTurnRecord:
        return CodexTurnRecord(
            turn_id=row["turn_id"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            correlation_id=row["correlation_id"],
            thread_id=row["thread_id"],
            backend=CodexBackendKind(row["backend"]),
            sandbox=SandboxMode(row["sandbox"]),
            approval_mode=ApprovalMode(row["approval_mode"]),
            cwd=row["cwd"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            runtime_evidence=json.loads(row["runtime_evidence"]),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> CodexEvent:
        from openjarvis.codex.types import CodexEventType

        return CodexEvent(
            event_id=row["event_id"],
            sequence=row["sequence"],
            occurred_at=row["occurred_at"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            thread_id=row["thread_id"],
            turn_id=row["turn_id"],
            item_id=row["item_id"],
            backend=CodexBackendKind(row["backend"]),
            event_type=CodexEventType(row["event_type"]),
            schema_version=row["schema_version"],
            payload=json.loads(row["payload"]),
        )


__all__ = [
    "CodexStateStore",
    "CodexThreadRecord",
    "CodexTurnRecord",
    "resolve_turn_model_evidence",
    "with_confirmed_model_evidence",
]
