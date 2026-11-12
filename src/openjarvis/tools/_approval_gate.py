"""Human-in-the-loop approval for tools that act on the user's computer.

The server-side agent has no TTY, so ``ToolSpec.requires_confirmation`` cannot
prompt anyone there. Tools that need a yes/no instead queue the action in the
existing approval store (``/v1/approvals``); the HUD shows it as an Approve /
Deny card and the tool waits for the decision.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

APPROVAL_WAIT_SECONDS = 120.0
_POLL_SECONDS = 0.5


class ApprovalOutcome:
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"


def request_approval(
    action_type: str,
    description: str,
    payload: Dict[str, Any],
    *,
    wait_seconds: float = APPROVAL_WAIT_SECONDS,
) -> str:
    """Queue *description* for the user and block until they decide.

    Returns one of the :class:`ApprovalOutcome` values. An undecided action is
    marked expired on timeout so it cannot be approved after the tool gave up.
    """
    try:
        from openjarvis.tools.approval_store import (
            STATUS_APPROVED,
            STATUS_DENIED,
            STATUS_EXECUTED,
            STATUS_EXPIRED,
            ApprovalStore,
        )
    except Exception:
        logger.warning("Approval store unavailable", exc_info=True)
        return ApprovalOutcome.UNAVAILABLE

    store = ApprovalStore()
    try:
        action = store.queue_action(
            action_type=action_type,
            description=description,
            payload=payload,
            permission_key=f"pc:{action_type}",
            tier="confirm",
            ttl_hours=1,
        )
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            current = store.get_action(action.id)
            status = current.status if current is not None else STATUS_DENIED
            if status == STATUS_APPROVED:
                store.update_status(action.id, STATUS_EXECUTED)
                return ApprovalOutcome.APPROVED
            if status in (STATUS_DENIED, STATUS_EXPIRED):
                return ApprovalOutcome.DENIED
            time.sleep(_POLL_SECONDS)
        store.update_status(action.id, STATUS_EXPIRED)
        return ApprovalOutcome.TIMED_OUT
    finally:
        try:
            store._conn.close()
        except Exception:
            pass


def outcome_message(outcome: str, what: str) -> str:
    if outcome == ApprovalOutcome.DENIED:
        return f"The user denied: {what}. Do not retry unless they ask again."
    if outcome == ApprovalOutcome.TIMED_OUT:
        return f"No approval within {int(APPROVAL_WAIT_SECONDS)}s for: {what}. Nothing was done."
    return f"Approval could not be requested for: {what}. Nothing was done."


__all__ = ["APPROVAL_WAIT_SECONDS", "ApprovalOutcome", "outcome_message", "request_approval"]
