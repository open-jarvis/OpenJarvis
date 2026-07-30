"""Central Phase-5 tool policy invariants."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from openjarvis.tasks.policy import (
    CentralRiskPolicy,
    RiskLevel,
    ToolPolicyContext,
)
from openjarvis.tasks.types import ExecutionLane
from openjarvis.tools.file_read import FileReadTool
from openjarvis.tools.shell_exec import ShellExecTool


def _context(**overrides) -> ToolPolicyContext:
    value = ToolPolicyContext(
        granted_capabilities=frozenset({"file:read"}),
        execution_lane=ExecutionLane.MODEL,
        requested_risk=RiskLevel.READ_ONLY,
        proposal_capability="file:read",
        allowed_roots=(Path("synthetic-root"),),
    )
    return replace(value, **overrides)


def test_read_tool_requires_trusted_capability_grant() -> None:
    decision = CentralRiskPolicy().authorize_tool(
        FileReadTool().manifest,
        _context(granted_capabilities=frozenset()),
    )
    assert decision.allowed is False
    assert decision.reason == "capability is not granted"


def test_model_cannot_create_a_capability() -> None:
    decision = CentralRiskPolicy().authorize_tool(
        FileReadTool().manifest,
        _context(proposal_capability="system:admin"),
    )
    assert decision.allowed is False
    assert "does not match" in decision.reason


def test_untrusted_input_can_raise_but_not_lower_risk() -> None:
    decision = CentralRiskPolicy().authorize_tool(
        FileReadTool().manifest,
        _context(untrusted_risk=RiskLevel.DESTRUCTIVE_OR_SENSITIVE),
    )
    assert decision.allowed is False
    assert decision.status == "waiting_approval"
    assert decision.effective_risk is RiskLevel.DESTRUCTIVE_OR_SENSITIVE

    already_sensitive = ShellExecTool().manifest
    lowered = CentralRiskPolicy().authorize_tool(
        already_sensitive,
        _context(
            granted_capabilities=frozenset({"code:execute"}),
            execution_lane=ExecutionLane.INTERACTIVE,
            proposal_capability="code:execute",
            requested_risk=RiskLevel.READ_ONLY,
            untrusted_risk=RiskLevel.READ_ONLY,
        ),
    )
    assert lowered.effective_risk is RiskLevel.DESTRUCTIVE_OR_SENSITIVE


def test_level_three_requires_exact_allow_once() -> None:
    manifest = ShellExecTool().manifest
    context = _context(
        granted_capabilities=frozenset({"code:execute"}),
        execution_lane=ExecutionLane.INTERACTIVE,
        proposal_capability="code:execute",
        requested_risk=RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
    )
    waiting = CentralRiskPolicy().authorize_tool(manifest, context)
    allowed = CentralRiskPolicy().authorize_tool(
        manifest,
        replace(context, approved_once=True),
    )
    assert waiting.status == "waiting_approval"
    assert allowed.allowed is True


def test_wrong_lane_is_denied() -> None:
    decision = CentralRiskPolicy().authorize_tool(
        FileReadTool().manifest,
        _context(execution_lane=ExecutionLane.INTERACTIVE),
    )
    assert decision.allowed is False
    assert "lane" in decision.reason
