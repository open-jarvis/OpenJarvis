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


@dataclass(frozen=True, slots=True)
class ToolPolicyContext:
    """Trusted runtime grants supplied by OpenJarvis, never by the model."""

    granted_capabilities: frozenset[str]
    execution_lane: ExecutionLane
    requested_risk: RiskLevel
    proposal_capability: str
    approved_once: bool = False
    untrusted_risk: RiskLevel = RiskLevel.READ_ONLY
    allowed_roots: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    """Auditable decision returned before a tool may execute."""

    allowed: bool
    status: str
    effective_risk: RiskLevel
    capability: str
    reason: str
    allowed_roots: tuple[Path, ...]


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
            payload.get("path") or payload.get("target") or payload.get("cwd") or ""
        )
        base = 1 if kind == "file_change" else 2
        return self.classify(
            requested_level=base,
            action=action,
            target=target,
        )

    def authorize_tool(
        self,
        manifest: Any,
        context: ToolPolicyContext,
    ) -> ToolPolicyDecision:
        """Apply the canonical Level 0-4 policy to one trusted manifest.

        ``manifest`` is intentionally duck-typed to avoid a dependency cycle:
        manifests import :class:`RiskLevel` from this module.  All authority
        comes from the code-owned manifest and ``ToolPolicyContext``.  A
        proposal may repeat those values for audit, but cannot grant them.
        """

        effective = RiskLevel(
            max(
                int(manifest.risk_level),
                int(context.requested_risk),
                int(context.untrusted_risk),
            )
        )
        roots = tuple(root.resolve(strict=False) for root in context.allowed_roots)

        def decision(allowed: bool, status: str, reason: str) -> ToolPolicyDecision:
            return ToolPolicyDecision(
                allowed=allowed,
                status=status,
                effective_risk=effective,
                capability=str(manifest.capability),
                reason=reason,
                allowed_roots=roots,
            )

        if not manifest.enabled:
            return decision(False, "denied", manifest.degraded_reason or "disabled")
        if not manifest.supports_current_platform():
            return decision(False, "denied", "unsupported platform")
        if context.proposal_capability != manifest.capability:
            return decision(
                False,
                "denied",
                "proposal capability does not match the trusted manifest",
            )
        if manifest.capability not in context.granted_capabilities:
            return decision(False, "denied", "capability is not granted")
        if context.execution_lane not in manifest.allowed_lanes:
            return decision(False, "denied", "tool is not allowed in this lane")
        if effective is RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL:
            return decision(False, "denied", "level-4 execution is disabled")
        if (
            manifest.required_approval
            or effective >= RiskLevel.DESTRUCTIVE_OR_SENSITIVE
        ) and not context.approved_once:
            return decision(False, "waiting_approval", "allow-once is required")
        return decision(True, "allowed", "trusted policy requirements satisfied")


__all__ = [
    "CentralRiskPolicy",
    "RiskLevel",
    "ToolPolicyContext",
    "ToolPolicyDecision",
    "TurnPolicy",
]
