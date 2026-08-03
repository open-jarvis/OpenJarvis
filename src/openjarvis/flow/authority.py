"""Single process-wide authority for Locked, Assistant, and Flow modes.

The browser never owns a Flow grant.  A native desktop process proves a fresh
OS authentication by signing a short-lived assertion with the per-process
bridge secret.  The secret is inherited by the backend only and is never
returned by an API endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from openjarvis.codex.types import ApprovalMode, SandboxMode
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext, ToolPolicyDecision
from openjarvis.tasks.types import ExecutionLane

FLOW_BRIDGE_SECRET_ENV = "OPENJARVIS_FLOW_BRIDGE_SECRET"
FLOW_MAX_SECONDS = 8 * 60 * 60
ASSERTION_MAX_AGE_SECONDS = 60

FLOW_CAPABILITIES: dict[str, str] = {
    "filesystem": "full_machine",
    "desktop": "full",
    "browser": "full",
    "shell": "elevated",
    "processes": "full",
    "services": "full",
    "registry": "full",
    "network": "full",
    "memory": "read_write",
    "git": "full",
    "package_management": "full",
    "application_control": "full",
}

ASSISTANT_CAPABILITIES: dict[str, str] = {
    "filesystem": "read_only",
    "desktop": "none",
    "browser": "read_only_isolated",
    "shell": "none",
    "processes": "none",
    "services": "none",
    "registry": "none",
    "network": "read_only",
    "memory": "read_only",
    "git": "read_only",
    "package_management": "none",
    "application_control": "none",
}


class AccessMode(str, Enum):
    LOCKED = "locked"
    ASSISTANT = "assistant"
    FLOW = "flow"


class FlowAuthenticationError(PermissionError):
    """A native assertion was absent, invalid, expired, or replayed."""


@dataclass(frozen=True, slots=True)
class FlowStatus:
    mode: AccessMode
    owner_authenticated: bool
    session_id: str | None
    activated_at: str | None
    expires_at: str | None
    last_activity_at: str | None
    remaining_seconds: int
    capabilities: dict[str, str]
    lock_reason: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mode"] = self.mode.value
        return value


@dataclass(frozen=True, slots=True)
class FlowTurnPolicy:
    sandbox: SandboxMode
    approval_mode: ApprovalMode
    execution_lane: ExecutionLane
    isolated_workspace: Path | None


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


class FlowSessionAuthority:
    """The only component allowed to grant local execution capabilities."""

    def __init__(
        self,
        bridge_secret: str | None = None,
        *,
        clock=time.time,
        max_session_seconds: int = FLOW_MAX_SECONDS,
    ) -> None:
        self._bridge_secret = (
            bridge_secret
            if bridge_secret is not None
            else os.environ.get(FLOW_BRIDGE_SECRET_ENV, "")
        )
        self._clock = clock
        self._max_session_seconds = max_session_seconds
        self._lock = threading.RLock()
        self._mode = AccessMode.LOCKED
        self._session_id: str | None = None
        self._activated_at: float | None = None
        self._expires_at: float | None = None
        self._last_activity_at: float | None = None
        self._lock_reason = "application_started"
        self._used_nonces: dict[str, float] = {}

    @classmethod
    def from_environment(cls) -> "FlowSessionAuthority":
        return cls(os.environ.get(FLOW_BRIDGE_SECRET_ENV, ""))

    def status(self) -> FlowStatus:
        with self._lock:
            self._expire_if_needed()
            now = self._clock()
            capabilities = (
                dict(FLOW_CAPABILITIES)
                if self._mode is AccessMode.FLOW
                else dict(ASSISTANT_CAPABILITIES)
                if self._mode is AccessMode.ASSISTANT
                else {}
            )
            return FlowStatus(
                mode=self._mode,
                owner_authenticated=self._mode is AccessMode.FLOW,
                session_id=self._session_id,
                activated_at=_iso(self._activated_at),
                expires_at=_iso(self._expires_at),
                last_activity_at=_iso(self._last_activity_at),
                remaining_seconds=(
                    max(0, int((self._expires_at or now) - now))
                    if self._mode is AccessMode.FLOW
                    else 0
                ),
                capabilities=capabilities,
                lock_reason=self._lock_reason,
            )

    @property
    def mode(self) -> AccessMode:
        return self.status().mode

    def is_flow(self) -> bool:
        return self.mode is AccessMode.FLOW

    def activate_assistant(self) -> FlowStatus:
        with self._lock:
            self._clear_flow("assistant_selected")
            self._mode = AccessMode.ASSISTANT
            return self.status()

    def activate_flow(
        self,
        *,
        nonce: str,
        authenticated_at: int,
        signature: str,
        owner: str,
    ) -> FlowStatus:
        with self._lock:
            self._verify_native_assertion(
                nonce=nonce,
                authenticated_at=authenticated_at,
                signature=signature,
                owner=owner,
            )
            now = self._clock()
            self._mode = AccessMode.FLOW
            self._session_id = secrets.token_urlsafe(32)
            self._activated_at = now
            self._expires_at = now + self._max_session_seconds
            self._last_activity_at = now
            self._lock_reason = ""
            return self.status()

    def record_activity(self, session_id: str | None = None) -> FlowStatus:
        with self._lock:
            self._expire_if_needed()
            if self._mode is AccessMode.FLOW:
                if session_id is not None and not hmac.compare_digest(
                    session_id, self._session_id or ""
                ):
                    raise FlowAuthenticationError("flow session does not match")
                self._last_activity_at = self._clock()
            return self.status()

    def lock(self, reason: str = "user_locked") -> FlowStatus:
        with self._lock:
            self._clear_flow(reason or "user_locked")
            return self.status()

    def derive_turn_policy(self, *, cwd: Path) -> FlowTurnPolicy:
        del cwd
        mode = self.mode
        if mode is AccessMode.FLOW:
            return FlowTurnPolicy(
                sandbox=SandboxMode.FULL_ACCESS,
                approval_mode=ApprovalMode.DENY_ALL,
                execution_lane=ExecutionLane.INTERACTIVE,
                isolated_workspace=None,
            )
        return FlowTurnPolicy(
            sandbox=SandboxMode.READ_ONLY,
            approval_mode=ApprovalMode.DENY_ALL,
            execution_lane=ExecutionLane.MODEL,
            isolated_workspace=None,
        )

    def authorize_tool(
        self,
        manifest: Any,
        context: ToolPolicyContext,
    ) -> ToolPolicyDecision:
        mode = self.mode
        effective = RiskLevel(
            min(
                int(RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL),
                max(
                    int(manifest.risk_level),
                    int(context.requested_risk),
                    int(context.untrusted_risk),
                ),
            )
        )
        allowed_roots = () if mode is AccessMode.FLOW else tuple(context.allowed_roots)

        def result(allowed: bool, reason: str) -> ToolPolicyDecision:
            return ToolPolicyDecision(
                allowed=allowed,
                status="allowed" if allowed else "denied",
                effective_risk=effective,
                capability=str(manifest.capability),
                reason=reason,
                allowed_roots=allowed_roots,
            )

        if not manifest.supports_current_platform():
            return result(False, "tool is unavailable on this operating system")
        if context.proposal_capability != manifest.capability:
            return result(False, "tool capability does not match its manifest")
        if mode is AccessMode.LOCKED:
            return result(False, "Locked mode does not allow personal tools")
        if mode is AccessMode.ASSISTANT:
            read_only = str(manifest.side_effect_class) in {
                "SideEffectClass.NONE",
                "SideEffectClass.LOCAL_READ",
                "none",
                "local_read",
            }
            return result(
                read_only,
                "Assistant mode allows read-only tools"
                if read_only
                else "Assistant mode is read-only",
            )
        return result(True, "active owner-authenticated Flow session")

    def _verify_native_assertion(
        self,
        *,
        nonce: str,
        authenticated_at: int,
        signature: str,
        owner: str,
    ) -> None:
        if len(self._bridge_secret) < 32:
            raise FlowAuthenticationError("native Flow bridge is unavailable")
        if not nonce or len(nonce) > 200 or not owner or len(owner) > 256:
            raise FlowAuthenticationError("native assertion is malformed")
        now = self._clock()
        if abs(now - authenticated_at) > ASSERTION_MAX_AGE_SECONDS:
            raise FlowAuthenticationError("native assertion expired")
        self._prune_nonces(now)
        if nonce in self._used_nonces:
            raise FlowAuthenticationError("native assertion was already used")
        message = f"flow-v1\n{nonce}\n{authenticated_at}\n{owner}".encode()
        expected = hmac.new(
            self._bridge_secret.encode(), message, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise FlowAuthenticationError("native assertion signature is invalid")
        self._used_nonces[nonce] = now

    def _expire_if_needed(self) -> None:
        if (
            self._mode is AccessMode.FLOW
            and self._expires_at is not None
            and self._clock() >= self._expires_at
        ):
            self._clear_flow("flow_session_expired")

    def _clear_flow(self, reason: str) -> None:
        self._mode = AccessMode.LOCKED
        self._session_id = None
        self._activated_at = None
        self._expires_at = None
        self._last_activity_at = None
        self._lock_reason = reason

    def _prune_nonces(self, now: float) -> None:
        self._used_nonces = {
            nonce: used_at
            for nonce, used_at in self._used_nonces.items()
            if now - used_at <= ASSERTION_MAX_AGE_SECONDS
        }


__all__ = [
    "ASSERTION_MAX_AGE_SECONDS",
    "ASSISTANT_CAPABILITIES",
    "FLOW_BRIDGE_SECRET_ENV",
    "FLOW_CAPABILITIES",
    "AccessMode",
    "FlowAuthenticationError",
    "FlowSessionAuthority",
    "FlowStatus",
    "FlowTurnPolicy",
]
