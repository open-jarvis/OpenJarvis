"""Strict, immutable domain models for deterministic trace evaluation."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from openjarvis.tasks.types import TaskStatus

SCHEMA_VERSION = "1.0"
DEFAULT_EVALUATOR_ID = "openjarvis.deterministic_trace_classifier"
DEFAULT_EVALUATOR_VERSION = "1.0.0"

Identifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
)


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


def new_evaluation_id() -> str:
    """Create an opaque identity that is intentionally excluded from hashes."""

    return f"evaluation_{uuid.uuid4().hex}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


def _redacted_text(value: str, *, field_name: str, maximum: int) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise ValueError(f"{field_name} contains secret-like material")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ValueError(f"{field_name} contains control characters")
    return value


class StrictFrozenModel(BaseModel):
    """Base for value objects that reject unknown fields and mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CanonicalTaskOutcome(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNING = "completed_with_warning"
    PARTIAL = "partial"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class EvaluationClass(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNING = "completed_with_warning"
    PARTIAL = "partial"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"
    POLICY_DENIED = "policy_denied"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    VERIFICATION_FAILED = "verification_failed"
    TOOL_FAILED = "tool_failed"
    BROWSER_FAILED = "browser_failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNSAFE_REQUEST = "unsafe_request"
    UNKNOWN_FAILURE = "unknown_failure"


class VerificationState(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ApprovalState(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"


class PolicyResult(str, Enum):
    NOT_REQUIRED = "not_required"
    NOT_EVALUATED = "not_evaluated"
    ALLOWED = "allowed"
    DENIED = "denied"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"


class EvidenceState(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class EvidenceType(str, Enum):
    TASK_STATE = "task_state"
    TASK_OUTCOME = "task_outcome"
    VERIFICATION_RESULT = "verification_result"
    POLICY_RESULT = "policy_result"
    APPROVAL_RESULT = "approval_result"
    TOOL_RESULT = "tool_result"
    BROWSER_RECOVERY_RESULT = "browser_recovery_result"
    BUDGET_RESULT = "budget_result"
    USER_CANCEL = "user_cancel"
    ARTIFACT_DIGEST = "artifact_digest"


class EvidenceSourceKind(str, Enum):
    TASK_RECORD = "task_record"
    TASK_EVENT = "task_event"
    APPROVAL_RECORD = "approval_record"
    POLICY_DECISION = "policy_decision"
    TOOL_ACTION = "tool_action"
    VERIFICATION_RECORD = "verification_record"
    BROWSER_RECOVERY = "browser_recovery"
    USAGE_RECORD = "usage_record"
    ARTIFACT = "artifact"
    TRACE_SNAPSHOT = "trace_snapshot"
    USER_EVENT = "user_event"


class EvidenceVerificationState(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICTING = "conflicting"


class TrustedBoundary(str, Enum):
    CANONICAL_RUNTIME = "canonical_runtime"
    EXPLICIT_USER = "explicit_user"
    EXTERNAL_UNTRUSTED = "external_untrusted"
    LEGACY_UNTRUSTED = "legacy_untrusted"


class ToolActionEndState(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    CANCELED = "canceled"
    PENDING = "pending"
    UNKNOWN = "unknown"


class BrowserRecoveryState(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    RECOVERED = "recovered"
    FAILED = "failed"
    UNKNOWN = "unknown"


class BudgetState(str, Enum):
    WITHIN_LIMITS = "within_limits"
    WARNING = "warning"
    EXCEEDED = "exceeded"
    UNKNOWN = "unknown"


class ExternalEffectState(str, Enum):
    NONE = "none"
    KNOWN = "known"
    UNKNOWN = "unknown"


class LegacyOutcomeHint(str, Enum):
    NONE = "none"
    SUCCESS = "success"
    FAILURE = "failure"
    OTHER = "other"


class FailureCategory(str, Enum):
    NONE = "none"
    PARTIAL = "partial"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"
    POLICY = "policy"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    VERIFICATION = "verification"
    TOOL = "tool"
    BROWSER = "browser"
    EVIDENCE = "evidence"
    EVIDENCE_CONFLICT = "evidence_conflict"
    BUDGET = "budget"
    UNSAFE_REQUEST = "unsafe_request"
    UNKNOWN_EFFECT = "unknown_effect"
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConfidenceBasis(str, Enum):
    FULL_CANONICAL_EVIDENCE = "full_canonical_evidence"
    SPECIFIC_TERMINAL_CAUSE = "specific_terminal_cause"
    MISSING_NON_BLOCKING_DATA = "missing_non_blocking_data"
    INCOMPLETE_CANONICAL_DATA = "incomplete_canonical_data"
    LEGACY_HINTS_IGNORED = "legacy_hints_ignored"
    CONFLICTING_CANONICAL_DATA = "conflicting_canonical_data"


class EvidenceReference(StrictFrozenModel):
    evidence_id: Identifier
    evidence_type: EvidenceType
    source_kind: EvidenceSourceKind
    source_id: Identifier
    digest: Digest
    verification_state: EvidenceVerificationState
    trusted_boundary: TrustedBoundary
    created_at: datetime

    _normalize_created_at = field_validator("created_at")(_as_utc)


class TaskStateSnapshot(StrictFrozenModel):
    event_id: Identifier
    sequence: int = Field(ge=0)
    status_from: TaskStatus | None = None
    status_to: TaskStatus
    occurred_at: datetime

    _normalize_occurred_at = field_validator("occurred_at")(_as_utc)


class ToolActionSnapshot(StrictFrozenModel):
    action_id: Identifier
    state: ToolActionEndState
    verification_state: VerificationState
    effect_known: bool
    exit_code: int | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)


class ToolResultSummary(StrictFrozenModel):
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    denied: int = Field(ge=0)
    canceled: int = Field(ge=0)
    pending: int = Field(ge=0)
    unknown: int = Field(ge=0)
    unknown_effects: int = Field(ge=0)
    zero_exit_codes: int = Field(ge=0)
    http_2xx: int = Field(ge=0)

    @classmethod
    def from_actions(
        cls,
        actions: tuple[ToolActionSnapshot, ...],
    ) -> ToolResultSummary:
        counts = {state: 0 for state in ToolActionEndState}
        for action in actions:
            counts[action.state] += 1
        return cls(
            total=len(actions),
            completed=counts[ToolActionEndState.COMPLETED],
            failed=counts[ToolActionEndState.FAILED],
            denied=counts[ToolActionEndState.DENIED],
            canceled=counts[ToolActionEndState.CANCELED],
            pending=counts[ToolActionEndState.PENDING],
            unknown=counts[ToolActionEndState.UNKNOWN],
            unknown_effects=sum(not action.effect_known for action in actions),
            zero_exit_codes=sum(action.exit_code == 0 for action in actions),
            http_2xx=sum(
                action.http_status is not None and 200 <= action.http_status < 300
                for action in actions
            ),
        )


class LegacyHints(StrictFrozenModel):
    """Bounded, explicitly untrusted compatibility hints.

    No model text is retained. These values are excluded from classification
    and confidence evidence, but remain part of the input digest for audit.
    """

    untrusted: Literal[True] = True
    trace_outcome: LegacyOutcomeHint = LegacyOutcomeHint.NONE
    model_claimed_success: bool = False
    feedback_score: float | None = Field(default=None, ge=0.0, le=1.0)
    judge_score: float | None = Field(default=None, ge=0.0, le=1.0)
    exit_code: int | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    skill_reported_success: bool | None = None
    teacher_recommended_success: bool | None = None

    def has_hints(self) -> bool:
        return any(
            (
                self.trace_outcome is not LegacyOutcomeHint.NONE,
                self.model_claimed_success,
                self.feedback_score is not None,
                self.judge_score is not None,
                self.exit_code is not None,
                self.http_status is not None,
                self.skill_reported_success is not None,
                self.teacher_recommended_success is not None,
            )
        )


class EvaluationInput(StrictFrozenModel):
    """Metadata-only, normalized input to the deterministic classifier."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    task_id: Identifier
    session_id: Identifier
    correlation_id: Identifier
    trace_id: Identifier
    task_type: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        ),
    ]
    requested_goal: str
    terminal_task_state: TaskStatus
    task_outcome: CanonicalTaskOutcome
    state_history: tuple[TaskStateSnapshot, ...] = ()
    verification_state: VerificationState
    approval_state: ApprovalState
    policy_result: PolicyResult
    tool_actions: tuple[ToolActionSnapshot, ...] = ()
    browser_recovery_state: BrowserRecoveryState
    evidence_state: EvidenceState
    budget_state: BudgetState
    user_canceled: bool = False
    turn_interrupted: bool = False
    external_effect_state: ExternalEffectState
    evidence_references: tuple[EvidenceReference, ...] = ()
    relevant_event_ids: tuple[Identifier, ...] = ()
    relevant_artifact_ids: tuple[Identifier, ...] = ()
    warnings: tuple[str, ...] = ()
    legacy_hints: LegacyHints = Field(default_factory=LegacyHints)

    @field_validator("requested_goal")
    @classmethod
    def _validate_requested_goal(cls, value: str) -> str:
        return _redacted_text(value, field_name="requested_goal", maximum=512)

    @field_validator("state_history")
    @classmethod
    def _sort_state_history(
        cls,
        values: tuple[TaskStateSnapshot, ...],
    ) -> tuple[TaskStateSnapshot, ...]:
        by_id: dict[str, TaskStateSnapshot] = {}
        for value in values:
            existing = by_id.get(value.event_id)
            if existing is not None and existing != value:
                raise ValueError("conflicting state events share an event_id")
            by_id[value.event_id] = value
        return tuple(
            sorted(by_id.values(), key=lambda item: (item.sequence, item.event_id))
        )

    @field_validator("tool_actions")
    @classmethod
    def _sort_tool_actions(
        cls,
        values: tuple[ToolActionSnapshot, ...],
    ) -> tuple[ToolActionSnapshot, ...]:
        by_id: dict[str, ToolActionSnapshot] = {}
        for value in values:
            existing = by_id.get(value.action_id)
            if existing is not None and existing != value:
                raise ValueError("conflicting tool actions share an action_id")
            by_id[value.action_id] = value
        return tuple(sorted(by_id.values(), key=lambda item: item.action_id))

    @field_validator("evidence_references")
    @classmethod
    def _sort_evidence(
        cls,
        values: tuple[EvidenceReference, ...],
    ) -> tuple[EvidenceReference, ...]:
        by_id: dict[str, EvidenceReference] = {}
        for value in values:
            existing = by_id.get(value.evidence_id)
            if existing is not None and existing != value:
                raise ValueError("conflicting evidence shares an evidence_id")
            by_id[value.evidence_id] = value
        return tuple(sorted(by_id.values(), key=lambda item: item.evidence_id))

    @field_validator("relevant_event_ids", "relevant_artifact_ids")
    @classmethod
    def _sort_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("warnings")
    @classmethod
    def _validate_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 20:
            raise ValueError("at most 20 warnings are allowed")
        normalized = {
            _redacted_text(value, field_name="warning", maximum=256) for value in values
        }
        return tuple(sorted(normalized))


class TraceEvaluation(StrictFrozenModel):
    """Immutable result produced by one evaluator version for one input."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    evaluation_id: Identifier = Field(default_factory=new_evaluation_id)
    evaluator_id: Identifier
    evaluator_version: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            pattern=r"^[0-9A-Za-z][0-9A-Za-z._+-]*$",
        ),
    ]
    task_id: Identifier
    session_id: Identifier
    correlation_id: Identifier
    trace_id: Identifier
    task_type: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        ),
    ]
    requested_goal: str
    terminal_task_state: TaskStatus
    task_outcome: CanonicalTaskOutcome
    evaluation_class: EvaluationClass
    verification_state: VerificationState
    approval_state: ApprovalState
    policy_result: PolicyResult
    evidence_state: EvidenceState
    tool_result_summary: ToolResultSummary
    failure_category: FailureCategory
    confidence: ConfidenceLevel
    confidence_basis: tuple[ConfidenceBasis, ...]
    evidence_references: tuple[EvidenceReference, ...]
    warnings: tuple[str, ...]
    created_at: datetime = Field(default_factory=utc_now)
    input_digest: Digest
    evaluation_hash: Digest

    _normalize_created_at = field_validator("created_at")(_as_utc)

    @field_validator("requested_goal")
    @classmethod
    def _validate_requested_goal(cls, value: str) -> str:
        return _redacted_text(value, field_name="requested_goal", maximum=512)

    @field_validator("confidence_basis")
    @classmethod
    def _sort_confidence_basis(
        cls,
        values: tuple[ConfidenceBasis, ...],
    ) -> tuple[ConfidenceBasis, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @field_validator("evidence_references")
    @classmethod
    def _sort_evidence(
        cls,
        values: tuple[EvidenceReference, ...],
    ) -> tuple[EvidenceReference, ...]:
        return EvaluationInput._sort_evidence(values)

    @field_validator("warnings")
    @classmethod
    def _validate_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return EvaluationInput._validate_warnings(values)

    def semantic_payload(self) -> dict[str, object]:
        """Return exactly the fields covered by ``evaluation_hash``."""

        return self.model_dump(
            mode="json",
            exclude={"evaluation_id", "created_at", "evaluation_hash"},
        )

    def recompute_hash(self) -> str:
        """Recompute the semantic SHA-256 without identity or wall-clock time."""

        serialized = json.dumps(
            self.semantic_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _evaluation_hash_matches_payload(self) -> TraceEvaluation:
        if self.evaluation_hash != self.recompute_hash():
            raise ValueError("evaluation_hash does not match the semantic payload")
        return self


__all__ = [
    "ApprovalState",
    "BrowserRecoveryState",
    "BudgetState",
    "CanonicalTaskOutcome",
    "ConfidenceBasis",
    "ConfidenceLevel",
    "DEFAULT_EVALUATOR_ID",
    "DEFAULT_EVALUATOR_VERSION",
    "Digest",
    "EvaluationClass",
    "EvaluationInput",
    "EvidenceReference",
    "EvidenceSourceKind",
    "EvidenceState",
    "EvidenceType",
    "EvidenceVerificationState",
    "ExternalEffectState",
    "FailureCategory",
    "Identifier",
    "LegacyHints",
    "LegacyOutcomeHint",
    "PolicyResult",
    "SCHEMA_VERSION",
    "TaskStateSnapshot",
    "ToolActionEndState",
    "ToolActionSnapshot",
    "ToolResultSummary",
    "TraceEvaluation",
    "TrustedBoundary",
    "VerificationState",
    "new_evaluation_id",
    "utc_now",
]
