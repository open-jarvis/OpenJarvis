from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest

from openjarvis.codex.types import ApprovalMode, SandboxMode
from openjarvis.flow import (
    AccessMode,
    FlowAuthenticationError,
    FlowSessionAuthority,
    WindowsSessionLockMonitor,
)
from openjarvis.tasks import ExecutionLane
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext
from openjarvis.tools.manifest import SideEffectClass

SECRET = "f" * 64


def _proof(timestamp: int, *, nonce: str = "fresh-native-nonce", owner: str = "owner"):
    message = f"flow-v1\n{nonce}\n{timestamp}\n{owner}".encode()
    return {
        "nonce": nonce,
        "authenticated_at": timestamp,
        "signature": hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest(),
        "owner": owner,
    }


def _manifest(side_effect: SideEffectClass):
    return SimpleNamespace(
        risk_level=RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL,
        capability="system:full",
        side_effect_class=side_effect,
        supports_current_platform=lambda: True,
    )


def _context() -> ToolPolicyContext:
    return ToolPolicyContext(
        granted_capabilities=frozenset(),
        execution_lane=ExecutionLane.MODEL,
        requested_risk=RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL,
        proposal_capability="system:full",
    )


def test_flow_requires_fresh_native_proof_and_cannot_be_replayed() -> None:
    now = 1_800_000_000
    authority = FlowSessionAuthority(SECRET, clock=lambda: now)
    assert authority.status().mode is AccessMode.LOCKED

    with pytest.raises(FlowAuthenticationError):
        authority.activate_flow(**{**_proof(now), "signature": "0" * 64})

    proof = _proof(now)
    status = authority.activate_flow(**proof)
    assert status.mode is AccessMode.FLOW
    assert status.owner_authenticated is True
    assert status.capabilities["filesystem"] == "full_machine"
    assert status.capabilities["memory"] == "read_write"

    authority.lock("test")
    with pytest.raises(FlowAuthenticationError, match="already used"):
        authority.activate_flow(**proof)


def test_flow_is_full_access_without_intermediate_approval() -> None:
    now = 1_800_000_000
    authority = FlowSessionAuthority(SECRET, clock=lambda: now)
    authority.activate_flow(**_proof(now))

    policy = authority.derive_turn_policy(cwd=__import__("pathlib").Path.cwd())
    assert policy.sandbox is SandboxMode.FULL_ACCESS
    assert policy.approval_mode is ApprovalMode.DENY_ALL
    assert policy.isolated_workspace is None
    assert authority.authorize_tool(
        _manifest(SideEffectClass.SECURITY_CRITICAL), _context()
    ).allowed


def test_assistant_is_read_only_and_expiry_relocks() -> None:
    clock = [1_800_000_000]
    authority = FlowSessionAuthority(
        SECRET,
        clock=lambda: clock[0],
        max_session_seconds=10,
    )
    authority.activate_assistant()
    assert authority.authorize_tool(
        _manifest(SideEffectClass.LOCAL_READ), _context()
    ).allowed
    assert not authority.authorize_tool(
        _manifest(SideEffectClass.DESTRUCTIVE), _context()
    ).allowed

    authority.activate_flow(**_proof(clock[0], nonce="another-fresh-nonce"))
    clock[0] += 11
    status = authority.status()
    assert status.mode is AccessMode.LOCKED
    assert status.lock_reason == "flow_session_expired"


def test_windows_lock_immediately_revokes_flow() -> None:
    now = 1_800_000_000
    authority = FlowSessionAuthority(SECRET, clock=lambda: now)
    authority.activate_flow(**_proof(now, nonce="windows-lock-proof"))
    monitor = WindowsSessionLockMonitor(
        authority.lock,
        is_flow=authority.is_flow,
        desktop_name=lambda: "Winlogon",
    )

    monitor.check_once()

    status = authority.status()
    assert status.mode is AccessMode.LOCKED
    assert status.lock_reason == "windows_session_locked"
