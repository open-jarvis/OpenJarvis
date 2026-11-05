"""REST endpoints for the proactive-agent approval queue."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from openjarvis.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    ApprovalStore,
    PendingAction,
)

try:
    from fastapi import APIRouter, HTTPException
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
async def list_pending_approvals() -> Dict[str, Any]:
    store = _get_store()
    store.expire_stale()
    actions = store.list_pending()
    return {"actions": [_serialize(a) for a in actions], "count": len(actions)}


@router.post("/v1/approvals/{action_id}/approve")
async def approve_action(action_id: str) -> Dict[str, Any]:
    store = _get_store()
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    store.update_status(action_id, STATUS_APPROVED)
    logger.info("Action %s approved via UI", action_id)
    return {"status": "approved", "id": action_id}


@router.post("/v1/approvals/{action_id}/deny")
async def deny_action(action_id: str) -> Dict[str, Any]:
    store = _get_store()
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    store.update_status(action_id, STATUS_DENIED)
    logger.info("Action %s denied via UI", action_id)
    return {"status": "denied", "id": action_id}


__all__ = ["router"]
