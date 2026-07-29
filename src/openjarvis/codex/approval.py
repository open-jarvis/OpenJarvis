"""Approval port for server-initiated Codex requests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ApprovalDecision(str, Enum):
    """App-server approval decisions."""

    ACCEPT = "accept"
    ACCEPT_FOR_SESSION = "acceptForSession"
    DECLINE = "decline"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Redacted approval request presented to an explicit broker."""

    request_id: str
    method: str
    thread_id: str | None
    turn_id: str | None
    item_id: str | None
    payload: dict[str, Any]


@runtime_checkable
class ApprovalBroker(Protocol):
    """Port implemented by a future UI or another explicit decision maker."""

    async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        """Resolve one request exactly once."""


class DenyApprovalBroker:
    """Safe default used when no approval UI or callback is connected."""

    async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        del request
        return ApprovalDecision.DECLINE


__all__ = [
    "ApprovalBroker",
    "ApprovalDecision",
    "ApprovalRequest",
    "DenyApprovalBroker",
]
