from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.codex.types import ApprovalMode, SandboxMode
from openjarvis.tasks import CentralRiskPolicy, ExecutionLane, RiskLevel


def test_read_only_policy_is_model_lane_and_deny_all(tmp_path: Path) -> None:
    policy = CentralRiskPolicy().derive_turn_policy(
        risk_level=0,
        cwd=tmp_path,
        isolated_workspace=None,
    )
    assert policy.risk_level is RiskLevel.READ_ONLY
    assert policy.sandbox is SandboxMode.READ_ONLY
    assert policy.approval_mode is ApprovalMode.DENY_ALL
    assert policy.execution_lane is ExecutionLane.MODEL


def test_reversible_workspace_policy_is_brokered(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = CentralRiskPolicy().derive_turn_policy(
        risk_level=1,
        cwd=workspace,
        isolated_workspace=workspace,
    )
    assert policy.sandbox is SandboxMode.WORKSPACE_WRITE
    assert policy.approval_mode is ApprovalMode.BROKERED
    assert policy.execution_lane is ExecutionLane.MODEL


def test_external_and_higher_risk_use_interactive_lane(tmp_path: Path) -> None:
    for level in (2, 3, 4):
        policy = CentralRiskPolicy().derive_turn_policy(
            risk_level=level,
            cwd=tmp_path,
            isolated_workspace=tmp_path,
        )
        assert policy.execution_lane is ExecutionLane.INTERACTIVE
        assert policy.approval_mode is ApprovalMode.BROKERED


def test_untrusted_description_can_raise_but_never_lower_risk() -> None:
    policy = CentralRiskPolicy()
    assert policy.classify(
        requested_level=0,
        action="prepare an email",
    ) is RiskLevel.EXTERNAL_PREPARATION
    assert policy.classify(
        requested_level=3,
        action="read file",
    ) is RiskLevel.DESTRUCTIVE_OR_SENSITIVE
    assert policy.classify(
        requested_level=0,
        action="transfer payment",
    ) is RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL


def test_write_policy_cannot_escape_isolated_workspace(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="inside"):
        CentralRiskPolicy().derive_turn_policy(
            risk_level=1,
            cwd=outside,
            isolated_workspace=isolated,
        )
