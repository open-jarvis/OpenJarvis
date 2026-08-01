from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from openjarvis.codex import (
    ApprovalMode,
    CodexBackendKind,
    CodexEvent,
    CodexEventType,
    CodexStateStore,
    CodexThreadRecord,
    CodexTurnRecord,
    SandboxMode,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _thread(
    *,
    correlation_id: str = "correlation-thread",
    thread_id: str = "thread-1",
) -> CodexThreadRecord:
    now = _now()
    return CodexThreadRecord(
        task_id="task-1",
        session_id="session-1",
        correlation_id=correlation_id,
        thread_id=thread_id,
        backend=CodexBackendKind.PYTHON_SDK,
        sandbox=SandboxMode.READ_ONLY,
        approval_mode=ApprovalMode.DENY_ALL,
        cwd="C:\\isolated",
        model_config={"model": None},
        status="started",
        created_at=now,
        updated_at=now,
    )


def _turn(*, task_id: str = "task-1") -> CodexTurnRecord:
    now = _now()
    return CodexTurnRecord(
        turn_id="turn-1",
        task_id=task_id,
        session_id="session-1",
        correlation_id="correlation-turn",
        thread_id="thread-1",
        backend=CodexBackendKind.PYTHON_SDK,
        sandbox=SandboxMode.READ_ONLY,
        approval_mode=ApprovalMode.DENY_ALL,
        cwd="C:\\isolated",
        status="started",
        created_at=now,
        updated_at=now,
    )


def test_store_enables_wal_and_foreign_keys(tmp_path: Path) -> None:
    store = CodexStateStore(tmp_path / "codex.db")

    assert store.journal_mode == "wal"
    assert store.foreign_keys_enabled is True
    store.close()


def test_thread_mapping_survives_process_restart(tmp_path: Path) -> None:
    path = tmp_path / "codex.db"
    first = CodexStateStore(path)
    first.save_thread(_thread())
    first.update_thread(
        "thread-1",
        status="idle",
        updated_at=_now(),
        resume_checkpoint="checkpoint-1",
    )
    first.close()

    reopened = CodexStateStore(path)
    record = reopened.get_thread("task-1", "session-1")

    assert record is not None
    assert record.thread_id == "thread-1"
    assert record.resume_checkpoint == "checkpoint-1"
    reopened.close()


def test_correlation_id_is_idempotent(tmp_path: Path) -> None:
    store = CodexStateStore(tmp_path / "codex.db")

    first = store.save_thread(_thread())
    second = store.save_thread(
        _thread(correlation_id="correlation-thread", thread_id="thread-other")
    )

    assert second == first
    assert store.list_threads() == [first]
    store.close()


def test_turn_requires_existing_thread(tmp_path: Path) -> None:
    store = CodexStateStore(tmp_path / "codex.db")

    with pytest.raises(sqlite3.IntegrityError):
        store.save_turn(_turn(task_id="missing"))
    store.close()


def test_turn_and_sequence_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "codex.db"
    store = CodexStateStore(path)
    store.save_thread(_thread())
    store.save_turn(_turn())

    assert store.next_sequence("thread-1") == 1
    store.close()

    reopened = CodexStateStore(path)
    assert reopened.get_turn("turn-1") is not None
    assert reopened.next_sequence("thread-1") == 2
    reopened.close()


def test_turn_runtime_evidence_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "codex.db"
    store = CodexStateStore(path)
    store.save_thread(_thread())
    evidence = {
        "requested_model": None,
        "actual_model": "gpt-confirmed",
        "actual_effort": "high",
        "evidence_source": "app_server_thread_start",
        "sdk_version": "0.144.4",
        "runtime_version": "0.144.4",
    }
    store.save_turn(replace(_turn(), runtime_evidence=evidence))
    store.close()

    reopened = CodexStateStore(path)
    record = reopened.get_turn("turn-1")

    assert record is not None
    assert record.backend is CodexBackendKind.PYTHON_SDK
    assert record.thread_id == "thread-1"
    assert record.runtime_evidence == evidence
    reopened.close()


def test_resume_evidence_replaces_old_partial_snapshot(tmp_path: Path) -> None:
    store = CodexStateStore(tmp_path / "codex.db")
    store.save_thread(
        replace(
            _thread(),
            model_config={
                "actual_model": "gpt-old",
                "actual_effort": "high",
                "evidence_source": "app_server_thread_start",
            },
        )
    )

    store.update_thread_model_evidence(
        "thread-1",
        actual_model="gpt-new",
        actual_effort=None,
        evidence_source="app_server_thread_resume",
    )
    partial = store.get_thread_by_id("thread-1")

    assert partial is not None
    assert partial.model_config["actual_model"] == "gpt-new"
    assert "actual_effort" not in partial.model_config
    assert partial.model_config["evidence_source"] == "app_server_thread_resume"

    store.update_thread_model_evidence(
        "thread-1",
        actual_model=None,
        actual_effort=None,
        evidence_source="app_server_thread_resume",
    )
    unknown = store.get_thread_by_id("thread-1")

    assert unknown is not None
    assert "actual_model" not in unknown.model_config
    assert "actual_effort" not in unknown.model_config
    assert "evidence_source" not in unknown.model_config
    store.close()


def test_existing_turn_schema_is_upgraded_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "legacy-codex.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE codex_turns (
            turn_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            correlation_id TEXT NOT NULL UNIQUE,
            thread_id TEXT NOT NULL,
            backend TEXT NOT NULL,
            sandbox TEXT NOT NULL,
            approval_mode TEXT NOT NULL,
            cwd TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO codex_turns VALUES (
            'legacy-turn', 'task', 'session', 'correlation', 'thread',
            'python_sdk', 'read_only', 'deny_all', 'C:\\isolated',
            'completed', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
        );
        """
    )
    connection.close()

    store = CodexStateStore(path)
    record = store.get_turn("legacy-turn")

    assert record is not None
    assert record.runtime_evidence == {}
    store.close()


def test_event_deduplication_and_redaction(tmp_path: Path) -> None:
    path = tmp_path / "codex.db"
    store = CodexStateStore(path)
    store.save_thread(_thread())
    sequence = store.next_sequence("thread-1")
    event = CodexEvent(
        event_id="event-1",
        sequence=sequence,
        occurred_at=_now(),
        task_id="task-1",
        session_id="session-1",
        thread_id="thread-1",
        turn_id=None,
        item_id=None,
        backend=CodexBackendKind.PYTHON_SDK,
        event_type=CodexEventType.THREAD_STARTED,
        payload={"accessToken": "must-not-persist", "status": "ok"},
    )

    assert store.save_event(event) is True
    assert store.save_event(event) is False
    loaded = store.list_events("thread-1")
    assert len(loaded) == 1
    assert loaded[0].payload["accessToken"] == "[REDACTED]"
    store.close()

    raw = path.read_bytes()
    assert b"must-not-persist" not in raw


def test_persistence_schema_has_required_mapping_fields(tmp_path: Path) -> None:
    path = tmp_path / "codex.db"
    store = CodexStateStore(path)
    store.close()
    connection = sqlite3.connect(path)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(codex_threads)")
    }
    connection.close()

    assert {
        "task_id",
        "session_id",
        "correlation_id",
        "thread_id",
        "backend",
        "sandbox",
        "approval_mode",
        "cwd",
        "status",
        "created_at",
        "updated_at",
        "last_event_sequence",
        "resume_checkpoint",
    } <= columns
