"""Persistent OpenJarvis broker for Codex command and file approvals."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from openjarvis.codex.approval import (
    ApprovalBroker,
    ApprovalDecision,
    ApprovalRequest,
)
from openjarvis.tasks.policy import CentralRiskPolicy
from openjarvis.tasks.service import TaskService
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import (
    ApprovalKind,
    ApprovalRecord,
    ApprovalStatus,
    InvalidTaskTransition,
    TaskStatus,
)


class PersistentApprovalBroker(ApprovalBroker):
    """Wait for explicit local decisions and answer each App Server request once."""

    def __init__(
        self,
        store: TaskStore,
        task_service: TaskService,
        *,
        risk_policy: CentralRiskPolicy | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._store = store
        self._tasks = task_service
        self._risk_policy = risk_policy or CentralRiskPolicy()
        self._timeout_seconds = timeout_seconds
        self._waiters: dict[str, asyncio.Event] = {}
        self._waiters_lock = asyncio.Lock()

    async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        """Persist, wait, and return one exact decision for a server request."""

        existing = self._store.get_approval_by_request(request.request_id)
        if existing is not None and existing.response_id:
            return self._codex_decision(existing)

        thread_id = request.thread_id or ""
        thread = self._store.get_thread_by_id(thread_id) if thread_id else None
        if thread is None:
            return ApprovalDecision.DECLINE
        task = self._store.get_task(thread.task_id)
        if task is None or task.session_id != thread.session_id:
            return ApprovalDecision.DECLINE

        kind = self._kind(request.method)
        action = self._action(request.payload, kind)
        target = self._target(request.payload, thread.cwd)
        effect = self._effect(request.payload, kind)
        risk = self._risk_policy.approval_risk(kind.value, request.payload)
        record = self._store.queue_approval(
            request_id=request.request_id,
            task_id=task.task_id,
            thread_id=thread.thread_id,
            turn_id=request.turn_id,
            item_id=request.item_id,
            action_id=self._optional_text(request.payload, "actionId", "action_id"),
            kind=kind,
            action=action,
            target=target,
            effect=effect,
            risk_level=int(risk),
            sandbox=thread.sandbox.value,
            cwd=thread.cwd,
            undo=self._undo(request.payload),
            payload=request.payload,
            ttl_seconds=self._timeout_seconds,
        )
        if record.response_id:
            return self._codex_decision(record)

        requested_event, inserted = self._store.append_event(
            task_id=task.task_id,
            source_event_id=f"approval:{record.approval_id}:requested",
            event_type="approval.requested",
            occurred_at=record.created_at,
            cause="codex_approval_request",
            component="approval_broker",
            thread_id=record.thread_id,
            turn_id=record.turn_id,
            item_id=record.item_id,
            approval_id=record.approval_id,
            action_id=record.action_id,
            payload=self._public_payload(record),
        )
        if inserted:
            self._tasks.project_committed(requested_event)

        current_task = self._store.get_task(task.task_id)
        if current_task is not None and current_task.status in {
            TaskStatus.RUNNING,
            TaskStatus.RECOVERING,
        }:
            try:
                self._tasks.transition(
                    task.task_id,
                    TaskStatus.WAITING_APPROVAL,
                    component="approval_broker",
                    cause="approval_wait_started",
                    idempotency_key=f"approval:{record.approval_id}:waiting",
                    payload={"approval_id": record.approval_id},
                )
            except InvalidTaskTransition:
                return ApprovalDecision.DECLINE

        record = await self._wait_for_decision(record)
        claimed = self._store.claim_approval_response(
            record.approval_id,
            response_id=record.response_id or uuid.uuid4().hex,
        )
        resolved_event, inserted = self._store.append_event(
            task_id=claimed.task_id,
            source_event_id=f"approval:{claimed.approval_id}:resolved",
            event_type="approval.resolved",
            occurred_at=claimed.decision_at or datetime.now().astimezone().isoformat(),
            cause="explicit_user_decision"
            if claimed.status is not ApprovalStatus.EXPIRED
            else "approval_timeout",
            component="approval_broker",
            thread_id=claimed.thread_id,
            turn_id=claimed.turn_id,
            item_id=claimed.item_id,
            approval_id=claimed.approval_id,
            action_id=claimed.action_id,
            payload={
                "approval_id": claimed.approval_id,
                "status": claimed.status.value,
                "decision": claimed.user_decision,
                "response_id": claimed.response_id,
            },
        )
        if inserted:
            self._tasks.project_committed(resolved_event)

        waiting_task = self._store.get_task(claimed.task_id)
        if (
            waiting_task is not None
            and waiting_task.status is TaskStatus.WAITING_APPROVAL
        ):
            self._tasks.transition(
                claimed.task_id,
                TaskStatus.RUNNING,
                component="approval_broker",
                cause="approval_response_ready",
                idempotency_key=f"approval:{claimed.approval_id}:resume",
                payload={
                    "approval_id": claimed.approval_id,
                    "decision": claimed.user_decision,
                },
            )
        return self._codex_decision(claimed)

    async def decide(
        self,
        approval_id: str,
        *,
        allow: bool,
        decision_id: str,
        actor: str,
    ) -> ApprovalRecord:
        """Record a validated local-user decision and wake its waiter."""

        if actor != "local_user":
            raise PermissionError("only an authenticated local user may decide")
        record = self._store.decide_approval(
            approval_id,
            allow=allow,
            decision_id=decision_id,
        )
        async with self._waiters_lock:
            waiter = self._waiters.get(approval_id)
            if waiter is not None:
                waiter.set()
        return record

    async def _wait_for_decision(self, record: ApprovalRecord) -> ApprovalRecord:
        current = self._store.get_approval(record.approval_id)
        if current is None:
            raise RuntimeError("persisted approval disappeared")
        if current.status is not ApprovalStatus.PENDING:
            return current

        async with self._waiters_lock:
            waiter = self._waiters.setdefault(record.approval_id, asyncio.Event())
        try:
            await asyncio.wait_for(waiter.wait(), timeout=self._timeout_seconds)
        except TimeoutError:
            current = self._store.expire_approval(
                record.approval_id,
                decision_id=f"timeout:{record.approval_id}",
            )
        else:
            current = self._store.get_approval(record.approval_id)
            if current is None:
                raise RuntimeError("approval decision disappeared")
        finally:
            async with self._waiters_lock:
                self._waiters.pop(record.approval_id, None)
        return current

    @staticmethod
    def _kind(method: str) -> ApprovalKind:
        lowered = method.lower()
        if "filechange" in lowered or "file_change" in lowered:
            return ApprovalKind.FILE_CHANGE
        return ApprovalKind.COMMAND

    @staticmethod
    def _action(payload: dict[str, Any], kind: ApprovalKind) -> str:
        value = (
            payload.get("command")
            or payload.get("changes")
            or payload.get("action")
            or kind.value
        )
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)

    @classmethod
    def _target(cls, payload: dict[str, Any], fallback: str) -> str:
        return cls._optional_text(payload, "path", "target", "cwd") or fallback

    @classmethod
    def _effect(cls, payload: dict[str, Any], kind: ApprovalKind) -> str:
        explicit = cls._optional_text(payload, "effect", "reason")
        if explicit:
            return explicit
        if kind is ApprovalKind.FILE_CHANGE:
            return "Apply the proposed file change in the isolated workspace."
        return "Execute the requested command under the displayed sandbox."

    @classmethod
    def _undo(cls, payload: dict[str, Any]) -> str:
        return (
            cls._optional_text(payload, "undo", "rollback")
            or "No automatic undo is guaranteed; inspect the isolated workspace diff."
        )

    @staticmethod
    def _optional_text(payload: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value)
        return None

    @staticmethod
    def _public_payload(record: ApprovalRecord) -> dict[str, Any]:
        return {
            "approval_id": record.approval_id,
            "kind": record.kind.value,
            "action": record.action,
            "target": record.target,
            "effect": record.effect,
            "risk_level": record.risk_level,
            "sandbox": record.sandbox,
            "cwd": record.cwd,
            "undo": record.undo,
            "expires_at": record.expires_at,
        }

    @staticmethod
    def _codex_decision(record: ApprovalRecord) -> ApprovalDecision:
        if record.status is ApprovalStatus.APPROVED:
            return ApprovalDecision.ACCEPT
        return ApprovalDecision.DECLINE


__all__ = ["PersistentApprovalBroker"]
