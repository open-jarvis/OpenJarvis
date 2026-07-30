from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from openjarvis.codex.store import CodexThreadRecord, CodexTurnRecord
from openjarvis.codex.types import ApprovalMode, CodexBackendKind, SandboxMode
from openjarvis.tasks import (
    ApprovalKind,
    RecoveryCoordinator,
    RecoveryDecision,
    TaskService,
    TaskStatus,
    TaskStore,
)


def _running_task(
    tmp_path: Path,
    *,
    risk_level: int = 0,
    with_thread: bool = True,
) -> tuple[TaskStore, TaskService]:
    store = TaskStore(tmp_path / "runtime.db")
    service = TaskService(store)
    task = service.create(
        task_id="task",
        session_id="session",
        correlation_id="correlation",
        description="resume read-only turn",
        backend="codex",
        risk_level=risk_level,
        component="test",
        cause="user_request",
        idempotency_key="create",
    )
    service.transition(
        task.task_id,
        TaskStatus.RUNNING,
        component="test",
        cause="turn_started",
        idempotency_key="running",
        active_thread_id="thread" if with_thread else None,
        active_turn_id="turn" if with_thread else None,
    )
    if with_thread:
        now = datetime.now(timezone.utc).isoformat()
        sandbox = (
            SandboxMode.READ_ONLY
            if risk_level == 0
            else SandboxMode.WORKSPACE_WRITE
        )
        approval = (
            ApprovalMode.DENY_ALL
            if risk_level == 0
            else ApprovalMode.BROKERED
        )
        store.save_thread(
            CodexThreadRecord(
                task_id="task",
                session_id="session",
                correlation_id="thread-correlation",
                thread_id="thread",
                backend=CodexBackendKind.PYTHON_SDK,
                sandbox=sandbox,
                approval_mode=approval,
                cwd=str(tmp_path),
                model_config={},
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        store.save_turn(
            CodexTurnRecord(
                turn_id="turn",
                task_id="task",
                session_id="session",
                correlation_id="turn-correlation",
                thread_id="thread",
                backend=CodexBackendKind.PYTHON_SDK,
                sandbox=sandbox,
                approval_mode=approval,
                cwd=str(tmp_path),
                status="running",
                created_at=now,
                updated_at=now,
            )
        )
    return store, service


def _event(store: TaskStore, event_type: str, item_id: str) -> None:
    store.append_event(
        task_id="task",
        source_event_id=f"{event_type}:{item_id}",
        event_type=event_type,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        cause="codex_event",
        component="test",
        thread_id="thread",
        turn_id="turn",
        item_id=item_id,
    )


@pytest.mark.asyncio
async def test_crash_before_command_can_resume_verified_read_only_turn(
    tmp_path: Path,
) -> None:
    store, service = _running_task(tmp_path)
    resumed: list[str] = []

    async def resume(task) -> None:
        resumed.append(task.task_id)

    try:
        reports = await RecoveryCoordinator(store, service).recover_all(
            resume_safe=resume
        )
        assert resumed == ["task"]
        assert reports[0].decision is RecoveryDecision.RESUMED_SAFE
        assert reports[0].safe_to_resume is True
        assert reports[0].final_status is TaskStatus.RUNNING
        assert service.get("task").status is not TaskStatus.DONE
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    ["during_command", "after_command_before_event_persistence"],
)
async def test_crash_with_unmatched_command_is_paused_as_ambiguous(
    tmp_path: Path,
    scenario: str,
) -> None:
    del scenario
    store, service = _running_task(tmp_path)
    _event(store, "command.started", "command")
    try:
        report = (await RecoveryCoordinator(store, service).recover_all())[0]
        assert report.decision is RecoveryDecision.PAUSED_AMBIGUOUS
        assert report.ambiguous_effect is True
        assert report.final_status is TaskStatus.PAUSED
        assert service.get("task").status is not TaskStatus.DONE
    finally:
        store.close()


@pytest.mark.asyncio
async def test_completed_command_event_removes_command_ambiguity(
    tmp_path: Path,
) -> None:
    store, service = _running_task(tmp_path)
    _event(store, "command.started", "command")
    _event(store, "command.completed", "command")
    try:
        report = (await RecoveryCoordinator(store, service).recover_all())[0]
        assert report.decision is RecoveryDecision.RESUME_AVAILABLE
        assert report.ambiguous_effect is False
        assert report.final_status is TaskStatus.PAUSED
    finally:
        store.close()


@pytest.mark.asyncio
async def test_crash_during_approval_keeps_approval_open(tmp_path: Path) -> None:
    store, service = _running_task(tmp_path)
    store.queue_approval(
        request_id="request",
        task_id="task",
        thread_id="thread",
        turn_id="turn",
        item_id="item",
        action_id=None,
        kind=ApprovalKind.COMMAND,
        action="read",
        target=str(tmp_path),
        effect="Read a file.",
        risk_level=1,
        sandbox="read_only",
        cwd=str(tmp_path),
        undo="No change.",
    )
    try:
        report = (await RecoveryCoordinator(store, service).recover_all())[0]
        assert report.decision is RecoveryDecision.WAITING_APPROVAL
        assert report.open_approval is True
        assert report.final_status is TaskStatus.WAITING_APPROVAL
    finally:
        store.close()


@pytest.mark.asyncio
async def test_restart_after_allow_before_app_server_response_waits_safely(
    tmp_path: Path,
) -> None:
    store, service = _running_task(tmp_path)
    approval = store.queue_approval(
        request_id="request",
        task_id="task",
        thread_id="thread",
        turn_id="turn",
        item_id="item",
        action_id=None,
        kind=ApprovalKind.FILE_CHANGE,
        action="edit file",
        target=str(tmp_path / "file.txt"),
        effect="Edit an isolated file.",
        risk_level=1,
        sandbox="workspace_write",
        cwd=str(tmp_path),
        undo="Restore the diff.",
    )
    store.decide_approval(
        approval.approval_id,
        allow=True,
        decision_id="user-allow",
    )
    try:
        report = (await RecoveryCoordinator(store, service).recover_all())[0]
        assert report.decision is RecoveryDecision.WAITING_APPROVAL
        assert report.open_approval is True
        assert store.get_approval(approval.approval_id).response_id is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_workspace_write_restart_never_auto_repeats_unclear_effect(
    tmp_path: Path,
) -> None:
    store, service = _running_task(tmp_path, risk_level=1)
    try:
        report = (await RecoveryCoordinator(store, service).recover_all())[0]
        assert report.decision is RecoveryDecision.PAUSED_AMBIGUOUS
        assert report.final_status is TaskStatus.PAUSED
        assert report.safe_to_resume is False
        assert service.get("task").status is not TaskStatus.DONE
    finally:
        store.close()


@pytest.mark.asyncio
async def test_missing_thread_pauses_and_records_recovery_check(
    tmp_path: Path,
) -> None:
    store, service = _running_task(tmp_path, with_thread=False)
    try:
        report = (await RecoveryCoordinator(store, service).recover_all())[0]
        assert report.decision is RecoveryDecision.PAUSED_NO_THREAD
        checks = store.list_recovery_checks("task")
        assert checks[0]["decision"] == "paused_no_thread"
        assert checks[0]["thread_id"] is None
    finally:
        store.close()
