"""SQLite-backed persistence for scheduled tasks and run logs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

_CREATE_TASKS_TABLE = """\
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              TEXT PRIMARY KEY,
    prompt          TEXT    NOT NULL,
    schedule_type   TEXT    NOT NULL,
    schedule_value  TEXT    NOT NULL,
    context_mode    TEXT    NOT NULL DEFAULT 'isolated',
    status          TEXT    NOT NULL DEFAULT 'active',
    next_run        TEXT,
    last_run        TEXT,
    agent           TEXT    NOT NULL DEFAULT 'simple',
    tools           TEXT    NOT NULL DEFAULT '',
    metadata        TEXT    NOT NULL DEFAULT '{}'
);
"""

_CREATE_LOGS_TABLE = """\
CREATE TABLE IF NOT EXISTS task_run_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    success     INTEGER NOT NULL DEFAULT 0,
    result      TEXT    NOT NULL DEFAULT '',
    error       TEXT    NOT NULL DEFAULT ''
);
"""

_INSERT_TASK = """\
INSERT OR REPLACE INTO scheduled_tasks
    (id, prompt, schedule_type, schedule_value, context_mode,
     status, next_run, last_run, agent, tools, metadata)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_LOG = """\
INSERT INTO task_run_logs
    (task_id, started_at, finished_at, success, result, error)
VALUES (?, ?, ?, ?, ?, ?)
"""


def parse_run_time(value: str) -> datetime:
    """Read legacy naive timestamps as UTC, not the host's local time."""
    value_dt = datetime.fromisoformat(value)
    if value_dt.tzinfo is None:
        return value_dt.replace(tzinfo=timezone.utc)
    return value_dt.astimezone(timezone.utc)


class SchedulerStore:
    """SQLite CRUD store for scheduled tasks and their run logs."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TASKS_TABLE)
        self._conn.execute(_CREATE_LOGS_TABLE)
        self._conn.commit()

    @classmethod
    def from_config(cls, config) -> SchedulerStore:
        """Open the same configured database for the CLI and server."""
        db_path = config.scheduler.db_path or config._config_dir / "scheduler.db"
        return cls(Path(db_path).expanduser() if db_path != ":memory:" else db_path)

    def worker_lock(self) -> FileLock | None:
        """Only one polling worker may execute tasks for a database."""
        if self._db_path == ":memory:":
            return None
        lock_path = f"{Path(self._db_path).resolve()}.worker.lock"
        return FileLock(lock_path, thread_local=False)

    # -- Task CRUD -----------------------------------------------------------

    def save_task(self, task: Dict[str, Any]) -> None:
        """Insert or replace a scheduled task record."""
        self._conn.execute(
            _INSERT_TASK,
            (
                task["id"],
                task["prompt"],
                task["schedule_type"],
                task["schedule_value"],
                task.get("context_mode", "isolated"),
                task.get("status", "active"),
                task.get("next_run"),
                task.get("last_run"),
                task.get("agent", "simple"),
                task.get("tools", ""),
                json.dumps(task.get("metadata", {})),
            ),
        )
        self._conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single task by ID, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all tasks, optionally filtered by *status*."""
        if status is not None:
            rows = self._conn.execute(
                "SELECT * FROM scheduled_tasks WHERE status = ?", (status,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM scheduled_tasks").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_due_tasks(self, now_iso: str) -> List[Dict[str, Any]]:
        """Return active tasks whose ``next_run`` is at or before *now_iso*."""
        now = parse_run_time(now_iso)
        rows = self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'active' "
            "AND next_run IS NOT NULL"
        )
        due = []
        for row in rows:
            try:
                run_at = parse_run_time(row["next_run"])
            except ValueError:
                continue  # A malformed legacy record must not block other tasks.
            if run_at <= now:
                due.append(self._row_to_dict(row))
        return due

    def update_task(self, task: Dict[str, Any]) -> None:
        """Update an existing task (same as save_task — uses INSERT OR REPLACE)."""
        self.save_task(task)

    def delete_task(self, task_id: str) -> None:
        """Delete a task by ID."""
        self._conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        self._conn.commit()

    # -- Run logs ------------------------------------------------------------

    def log_run(
        self,
        task_id: str,
        started_at: str,
        finished_at: str,
        success: bool,
        result: str = "",
        error: str = "",
    ) -> None:
        """Record a single execution of a task."""
        self._conn.execute(
            _INSERT_LOG,
            (task_id, started_at, finished_at, int(success), result, error),
        )
        self._conn.commit()

    def get_run_logs(self, task_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recent run logs for *task_id*."""
        rows = self._conn.execute(
            "SELECT * FROM task_run_logs WHERE task_id = ? ORDER BY id DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        if "metadata" in d and isinstance(d["metadata"], str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        return d


__all__ = ["SchedulerStore"]
