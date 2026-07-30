"""Structured proposal, action, verification, and artifact records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.tasks.policy import RiskLevel
from openjarvis.tools.manifest import SideEffectClass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ParameterSource(str, Enum):
    USER = "user"
    SYSTEM = "system"
    TASK = "task"
    WEBSITE = "website"
    MEMORY = "memory"
    TOOL_OUTPUT = "tool_output"


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    DENIED = "denied"
    WAITING_APPROVAL = "waiting_approval"
    RUNNING = "running"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ToolProposal(BaseModel):
    """Only model-originated action shape accepted by OpenJarvis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(default_factory=lambda: _id("proposal"), min_length=1)
    task_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    arguments: dict[str, Any]
    expected_result: str = Field(min_length=1)
    expected_side_effect: SideEffectClass
    risk_level: RiskLevel
    capability: str = Field(min_length=1)
    target: str = Field(min_length=1)
    verification_plan: str = Field(min_length=1)
    undo_plan: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=256)
    timeout_seconds: float = Field(gt=0, le=300)
    rationale: str = Field(min_length=1)
    parameter_sources: dict[str, ParameterSource]
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _all_arguments_have_sources(self) -> "ToolProposal":
        arguments = set(self.arguments)
        sources = set(self.parameter_sources)
        if arguments != sources:
            missing = arguments - sources
            extra = sources - arguments
            details = []
            if missing:
                details.append("missing: " + ", ".join(sorted(missing)))
            if extra:
                details.append("extra: " + ", ".join(sorted(extra)))
            raise ValueError("parameter_sources mismatch (" + "; ".join(details) + ")")
        return self


class ToolAction(BaseModel):
    """Persistent execution record controlled by OpenJarvis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(default_factory=lambda: _id("action"), min_length=1)
    proposal_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    approval_id: str | None = None
    tool_run_id: str | None = None
    tool_id: str = Field(min_length=1)
    manifest_version: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    risk_level: RiskLevel
    target: str = Field(min_length=1)
    expected_side_effect: SideEffectClass
    verification_plan: str = Field(min_length=1)
    undo_plan: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: ActionStatus = ActionStatus.PROPOSED
    verification_status: VerificationStatus = VerificationStatus.PENDING
    output_summary: str = ""
    error: str = ""
    retry_count: int = Field(default=0, ge=0, le=1)
    effect_known: bool = True
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    @classmethod
    def from_proposal(
        cls,
        proposal: ToolProposal,
        *,
        manifest_version: str,
        effective_risk: RiskLevel,
    ) -> "ToolAction":
        return cls(
            proposal_id=proposal.proposal_id,
            task_id=proposal.task_id,
            session_id=proposal.session_id,
            correlation_id=proposal.correlation_id,
            thread_id=proposal.thread_id,
            turn_id=proposal.turn_id,
            item_id=proposal.item_id,
            tool_id=proposal.tool_id,
            manifest_version=manifest_version,
            capability=proposal.capability,
            risk_level=effective_risk,
            target=proposal.target,
            expected_side_effect=proposal.expected_side_effect,
            verification_plan=proposal.verification_plan,
            undo_plan=proposal.undo_plan,
            idempotency_key=proposal.idempotency_key,
        )


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    observed_state: str = Field(min_length=1)
    expected_state: str = Field(min_length=1)
    artifact_ids: tuple[str, ...] = ()


class ToolArtifact(BaseModel):
    """Metadata-only reference to a bounded out-of-line artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(default_factory=lambda: _id("artifact"), min_length=1)
    task_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    approval_id: str | None = None
    tool_run_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    redacted: bool = False
    restore_of: str | None = None
    created_at: str = Field(default_factory=utc_now)


TOOL_EVENT_TYPES = frozenset(
    {
        "tool.proposed",
        "tool.validated",
        "tool.denied",
        "tool.waiting_approval",
        "tool.started",
        "tool.output",
        "tool.verification_started",
        "tool.verified",
        "tool.verification_failed",
        "tool.completed",
        "tool.failed",
        "tool.canceled",
        "tool.undo_prepared",
        "tool.undo_applied",
        "browser.health_checked",
        "browser.recovery_started",
        "browser.reconnected",
        "browser.recovery_failed",
        "desktop.focus_acquired",
        "desktop.action_performed",
        "desktop.action_verified",
    }
)


class ToolEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: _id("event"), min_length=1)
    event_type: str
    task_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    approval_id: str | None = None
    tool_run_id: str | None = None
    artifact_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str = Field(default_factory=utc_now)

    @field_validator("event_type")
    @classmethod
    def _known_event(cls, value: str) -> str:
        if value not in TOOL_EVENT_TYPES:
            raise ValueError(f"unknown tool event: {value}")
        return value


__all__ = [
    "ActionStatus",
    "ParameterSource",
    "TOOL_EVENT_TYPES",
    "ToolAction",
    "ToolArtifact",
    "ToolEvent",
    "ToolProposal",
    "VerificationResult",
    "VerificationStatus",
    "utc_now",
]
