"""REST endpoints for the proactive-agent approval queue."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from openjarvis.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    ApprovalStore,
    PendingAction,
)

try:
    from fastapi import APIRouter, Header, HTTPException, Request
except ImportError:
    raise ImportError("fastapi is required for approval routes")

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton that shares the same DB file as ProactiveAgent (WAL mode is safe)
_store: Optional[ApprovalStore] = None


def _get_store() -> ApprovalStore:
    global _store
    if _store is None:
        _store = ApprovalStore()
    return _store


def _serialize(action: PendingAction) -> Dict[str, Any]:
    return {
        "id": action.id,
        "action_type": action.action_type,
        "description": action.description,
        "payload": action.payload,
        "permission_key": action.permission_key,
        "tier": action.tier,
        "status": action.status,
        "created_at": action.created_at,
        "expires_at": action.expires_at,
    }


@router.get("/v1/approvals/pending")
async def list_pending_approvals(request: Request) -> Dict[str, Any]:
    from openjarvis.server.task_routes import _require_local

    _require_local(request)
    store = _get_store()
    store.expire_stale()
    actions = [_serialize(action) for action in store.list_pending()]
    task_store = getattr(request.app.state, "task_store", None)
    if task_store is not None:
        from openjarvis.server.task_routes import serialize_approval

        actions.extend(
            serialize_approval(record)
            for record in task_store.list_pending_approvals()
        )
    return {"actions": actions, "count": len(actions)}


@router.post("/v1/approvals/{action_id}/approve")
async def approve_action(
    action_id: str,
    request: Request,
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
    ),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
) -> Dict[str, Any]:
    from openjarvis.server.task_routes import _require_local

    _require_local(request)
    task_store = getattr(request.app.state, "task_store", None)
    task_approval = (
        task_store.get_approval(action_id) if task_store is not None else None
    )
    if task_approval is not None:
        return await _decide_task_approval(
            request,
            task_approval,
            allow=True,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    store = _get_store()
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    store.update_status(action_id, STATUS_APPROVED)
    logger.info("Action %s approved via UI", action_id)
    return {"status": "approved", "id": action_id}


@router.post("/v1/approvals/{action_id}/deny")
async def deny_action(
    action_id: str,
    request: Request,
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
    ),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
) -> Dict[str, Any]:
    from openjarvis.server.task_routes import _require_local

    _require_local(request)
    task_store = getattr(request.app.state, "task_store", None)
    task_approval = (
        task_store.get_approval(action_id) if task_store is not None else None
    )
    if task_approval is not None:
        return await _decide_task_approval(
            request,
            task_approval,
            allow=False,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    store = _get_store()
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    store.update_status(action_id, STATUS_DENIED)
    logger.info("Action %s denied via UI", action_id)
    return {"status": "denied", "id": action_id}


async def _decide_task_approval(
    request: Request,
    approval,
    *,
    allow: bool,
    correlation_id: str | None,
    idempotency_key: str | None,
) -> Dict[str, Any]:
    """Apply one authenticated local decision to the Phase 3 broker."""

    from openjarvis.server.task_routes import (
        _require_local,
        _validated_header,
    )

    _require_local(request)
    if correlation_id is None or idempotency_key is None:
        raise HTTPException(
            status_code=422,
            detail="X-Correlation-ID and Idempotency-Key are required",
        )
    correlation_id = _validated_header(correlation_id, "X-Correlation-ID")
    idempotency_key = _validated_header(idempotency_key, "Idempotency-Key")
    broker = getattr(request.app.state, "approval_broker", None)
    service = getattr(request.app.state, "task_service", None)
    if broker is None or service is None:
        raise HTTPException(
            status_code=503,
            detail="Codex approval capability is disabled",
        )
    tool_actions = getattr(request.app.state, "tool_action_service", None)
    tool_action = (
        tool_actions.store.get_action(approval.action_id)
        if tool_actions is not None and approval.action_id
        else None
    )
    try:
        if tool_action is not None:
            if allow:
                tool_action = await tool_actions.approve(
                    tool_action.action_id, decision_id=idempotency_key
                )
            else:
                tool_action = tool_actions.deny(
                    tool_action.action_id, decision_id=idempotency_key
                )
            record = service.store.get_approval(approval.approval_id)
            if record is None:
                raise ValueError("approval record disappeared")
            from openjarvis.tasks.types import TaskStatus

            current_task = service.get(approval.task_id)
            if (
                current_task is not None
                and current_task.status is TaskStatus.WAITING_APPROVAL
            ):
                service.transition(
                    approval.task_id,
                    TaskStatus.RUNNING,
                    component="approval_api",
                    cause="canonical_tool_approval_decided",
                    idempotency_key=f"tool-approval-resume:{idempotency_key}",
                    active_thread_id=approval.thread_id,
                    active_turn_id=approval.turn_id,
                    payload={
                        "action_id": tool_action.action_id,
                        "action_status": tool_action.status.value,
                        "decision": "allow" if allow else "deny",
                    },
                )
        else:
            record = await broker.decide(
                approval.approval_id,
                allow=allow,
                decision_id=idempotency_key,
                actor="local_user",
            )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    event, created = service.store.append_event(
        task_id=approval.task_id,
        source_event_id=f"api-approval:{idempotency_key}",
        event_type="approval.user_decided",
        occurred_at=datetime.now(timezone.utc).isoformat(),
        cause="local_user_approval_decision",
        component="approval_api",
        thread_id=approval.thread_id,
        turn_id=approval.turn_id,
        item_id=approval.item_id,
        approval_id=approval.approval_id,
        action_id=approval.action_id,
        payload={
            "decision": "allow" if allow else "deny",
            "request_correlation_id": correlation_id,
        },
    )
    if created:
        service.project_committed(event)
    logger.info(
        "Codex approval %s decided via local UI: %s",
        approval.approval_id,
        record.status.value,
    )
    return {"status": record.status.value, "id": record.approval_id}


__all__ = ["router"]
