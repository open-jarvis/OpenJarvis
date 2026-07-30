"""Central risk classification and Codex permission derivation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from openjarvis.codex.types import ApprovalMode, SandboxMode
from openjarvis.tasks.types import ExecutionLane


class RiskLevel(IntEnum):
    """Canonical action risk levels."""

    READ_ONLY = 0
    REVERSIBLE_WORKSPACE = 1
    EXTERNAL_PREPARATION = 2
    DESTRUCTIVE_OR_SENSITIVE = 3
    FINANCIAL_OR_SECURITY_CRITICAL = 4


@dataclass(frozen=True, slots=True)
class TurnPolicy:
    """Permissions derived by OpenJarvis before a Codex turn."""

    risk_level: RiskLevel
    sandbox: SandboxMode
    approval_mode: ApprovalMode
    execution_lane: ExecutionLane
    isolated_workspace: Path | None


class CentralRiskPolicy:
    """Only authority allowed to derive Codex sandbox and approval mode."""

    _CRITICAL_MARKERS = (
        "payment",
        "purchase",
        "transfer",
        "credential",
        "firewall",
        "encryption key",
    )
    _DESTRUCTIVE_MARKERS = (
        "delete",
        "remove",
        "drop",
        "reset --hard",
        "format",
        "shutdown",
        "publish",
        "send",
    )
    _EXTERNAL_MARKERS = (
        "browser",
        "desktop",
        "email",
        "message",
        "network",
        "upload",
    )

    def classify(
        self,
        *,
        requested_level: int,
        action: str = "",
        target: str = "",
    ) -> RiskLevel:
        """Increase risk from untrusted descriptions, never decrease it."""

        try:
            level = RiskLevel(requested_level)
        except ValueError as exc:
            raise ValueError("risk level must be between 0 and 4") from exc
        text = f"{action} {target}".lower()
        if any(marker in text for marker in self._CRITICAL_MARKERS):
            level = max(level, RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL)
        elif any(marker in text for marker in self._DESTRUCTIVE_MARKERS):
            level = max(level, RiskLevel.DESTRUCTIVE_OR_SENSITIVE)
        elif any(marker in text for marker in self._EXTERNAL_MARKERS):
            level = max(level, RiskLevel.EXTERNAL_PREPARATION)
        return RiskLevel(level)

    def derive_turn_policy(
        self,
        *,
        risk_level: int,
        cwd: Path,
        isolated_workspace: Path | None,
    ) -> TurnPolicy:
        """Derive permissions from trusted OpenJarvis configuration only."""

        level = RiskLevel(risk_level)
        resolved_cwd = cwd.resolve(strict=False)
        if level is RiskLevel.READ_ONLY:
            return TurnPolicy(
                risk_level=level,
                sandbox=SandboxMode.READ_ONLY,
                approval_mode=ApprovalMode.DENY_ALL,
                execution_lane=ExecutionLane.MODEL,
                isolated_workspace=None,
            )
        if isolated_workspace is None:
            raise ValueError("risk levels 1-4 require an isolated workspace")
        root = isolated_workspace.resolve(strict=False)
        try:
            resolved_cwd.relative_to(root)
        except ValueError as exc:
            raise ValueError("cwd must remain inside the isolated workspace") from exc
        lane = (
            ExecutionLane.INTERACTIVE
            if level >= RiskLevel.EXTERNAL_PREPARATION
            else ExecutionLane.MODEL
        )
        return TurnPolicy(
            risk_level=level,
            sandbox=SandboxMode.WORKSPACE_WRITE,
            approval_mode=ApprovalMode.BROKERED,
            execution_lane=lane,
            isolated_workspace=root,
        )

    def approval_risk(self, kind: str, payload: dict[str, Any]) -> RiskLevel:
        """Classify a request without treating its text as authorization."""

        action = str(
            payload.get("command")
            or payload.get("action")
            or payload.get("reason")
            or kind
        )
        target = str(
            payload.get("path")
            or payload.get("target")
            or payload.get("cwd")
            or ""
        )
        base = 1 if kind == "file_change" else 2
        return self.classify(
            requested_level=base,
            action=action,
            target=target,
        )


__all__ = ["CentralRiskPolicy", "RiskLevel", "TurnPolicy"]
