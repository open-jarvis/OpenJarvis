from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openjarvis.codex.approval import ApprovalDecision, ApprovalRequest
from openjarvis.codex.store import CodexThreadRecord
from openjarvis.codex.types import ApprovalMode, CodexBackendKind, SandboxMode
from openjarvis.tasks import (
    ApprovalStatus,
    PersistentApprovalBroker,
    TaskService,
    TaskStatus,
    TaskStore,
)


def _runtime(
    tmp_path: Path,
    *,
    timeout: float = 1.0,
) -> tuple[TaskStore, TaskService, PersistentApprovalBroker]:
    store = TaskStore(tmp_path / "runtime.db")
    service = TaskService(store)
    task = service.create(
        task_id="task",
        session_id="session",
        correlation_id="task-correlation",
        description="write in isolated workspace",
        backend="codex",
        risk_level=1,
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
        active_thread_id="thread",
        active_turn_id="turn",
    )
    store.save_thread(
        CodexThreadRecord(
            task_id="task",
            session_id="session",
            correlation_id="thread-correlation",
            thread_id="thread",
            backend=CodexBackendKind.APP_SERVER,
            sandbox=SandboxMode.WORKSPACE_WRITE,
            approval_mode=ApprovalMode.BROKERED,
            cwd=str(tmp_path),
            model_config={},
            status="active",
            created_at="2026-07-30T00:00:00+00:00",
            updated_at="2026-07-30T00:00:00+00:00",
        )
    )
    return (
        store,
        service,
        PersistentApprovalBroker(store, service, timeout_seconds=timeout),
    )


def _request(request_id: str = "request-1") -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        method="item/commandExecution/requestApproval",
        thread_id="thread",
        turn_id="turn",
        item_id="item",
        payload={
            "command": ["python", "-m", "compileall", "."],
            "cwd": "isolated",
            "effect": "Compile files in the isolated workspace.",
        },
    )


async def _wait_for_pending(store: TaskStore) -> str:
    for _ in range(100):
        pending = store.list_pending_approvals()
        if pending:
            return pending[0].approval_id
        await asyncio.sleep(0.005)
    raise AssertionError("approval did not become pending")


@pytest.mark.asyncio
async def test_approval_wait_and_allow_exactly_once(tmp_path: Path) -> None:
    store, service, broker = _runtime(tmp_path)
    try:
        resolving = asyncio.create_task(broker.resolve(_request()))
        approval_id = await _wait_for_pending(store)
        assert service.get("task").status is TaskStatus.WAITING_APPROVAL

        first = await broker.decide(
            approval_id,
            allow=True,
            decision_id="decision-1",
            actor="local_user",
        )
        repeated = await broker.decide(
            approval_id,
            allow=True,
            decision_id="decision-2",
            actor="local_user",
        )
        assert repeated.decision_id == first.decision_id
        assert await resolving is ApprovalDecision.ACCEPT

        record = store.get_approval(approval_id)
        assert record is not None
        assert record.status is ApprovalStatus.APPROVED
        assert record.response_id
        assert service.get("task").status is TaskStatus.RUNNING
        resolved_events = [
            event
            for event in service.timeline("task")
            if event.event_type == "approval.resolved"
        ]
        assert len(resolved_events) == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_approval_deny_and_conflicting_duplicate(tmp_path: Path) -> None:
    store, _, broker = _runtime(tmp_path)
    try:
        resolving = asyncio.create_task(broker.resolve(_request()))
        approval_id = await _wait_for_pending(store)
        await broker.decide(
            approval_id,
            allow=False,
            decision_id="deny-1",
            actor="local_user",
        )
        with pytest.raises(ValueError, match="conflicting"):
            await broker.decide(
                approval_id,
                allow=True,
                decision_id="allow-late",
                actor="local_user",
            )
        assert await resolving is ApprovalDecision.DECLINE
    finally:
        store.close()


@pytest.mark.asyncio
async def test_approval_timeout_denies(tmp_path: Path) -> None:
    store, _, broker = _runtime(tmp_path, timeout=0.02)
    try:
        assert await broker.resolve(_request()) is ApprovalDecision.DECLINE
        record = store.get_approval_by_request("request-1")
        assert record is not None
        assert record.status is ApprovalStatus.EXPIRED
        assert record.response_id
    finally:
        store.close()


@pytest.mark.asyncio
async def test_non_local_actor_cannot_approve(tmp_path: Path) -> None:
    store, _, broker = _runtime(tmp_path)
    try:
        resolving = asyncio.create_task(broker.resolve(_request()))
        approval_id = await _wait_for_pending(store)
        with pytest.raises(PermissionError):
            await broker.decide(
                approval_id,
                allow=True,
                decision_id="model-decision",
                actor="model",
            )
        await broker.decide(
            approval_id,
            allow=False,
            decision_id="user-deny",
            actor="local_user",
        )
        assert await resolving is ApprovalDecision.DECLINE
    finally:
        store.close()


@pytest.mark.asyncio
async def test_restart_after_user_decision_reuses_one_response(tmp_path: Path) -> None:
    store, service, broker = _runtime(tmp_path)
    try:
        first_run = asyncio.create_task(broker.resolve(_request()))
        approval_id = await _wait_for_pending(store)
        store.decide_approval(
            approval_id,
            allow=True,
            decision_id="persisted-user-decision",
        )
        first_run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_run

        restarted = PersistentApprovalBroker(store, service, timeout_seconds=1)
        assert await restarted.resolve(_request()) is ApprovalDecision.ACCEPT
        first_response = store.get_approval(approval_id).response_id
        assert first_response
        assert await restarted.resolve(_request()) is ApprovalDecision.ACCEPT
        assert store.get_approval(approval_id).response_id == first_response
    finally:
        store.close()
