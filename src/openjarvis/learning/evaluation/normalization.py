"""Pure normalization and canonical hashing for evaluation snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from openjarvis.browser.models import BrowserRecoveryRecord
from openjarvis.learning.evaluation.models import (
    ApprovalState,
    BrowserRecoveryState,
    BudgetState,
    CanonicalTaskOutcome,
    EvaluationInput,
    EvidenceReference,
    EvidenceState,
    ExternalEffectState,
    LegacyHints,
    LegacyOutcomeHint,
    PolicyResult,
    TaskStateSnapshot,
    ToolActionEndState,
    ToolActionSnapshot,
    VerificationState,
)
from openjarvis.tasks.policy import ToolPolicyDecision
from openjarvis.tasks.types import (
    ApprovalRecord,
    ApprovalStatus,
    TaskEvent,
    TaskOutcome,
    TaskRecord,
    TaskUsage,
)
from openjarvis.tools.actions import (
    ActionStatus,
    ToolAction,
)
from openjarvis.tools.actions import (
    VerificationStatus as RuntimeVerificationStatus,
)


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically with stable keys and separators."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_digest(value: Any) -> str:
    """Hash a canonical JSON representation using SHA-256."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_snapshot(
    snapshot: EvaluationInput | Mapping[str, Any],
) -> EvaluationInput:
    """Validate and reconstruct a snapshot in canonical tuple order."""

    if isinstance(snapshot, EvaluationInput):
        payload = snapshot.model_dump(mode="python", exclude_none=False)
    else:
        payload = dict(snapshot)
    return EvaluationInput.model_validate(payload)


def input_digest(snapshot: EvaluationInput | Mapping[str, Any]) -> str:
    """Return the identity digest of the normalized metadata-only input."""

    return sha256_digest(normalize_snapshot(snapshot))


def normalize_legacy_outcome(value: str | None) -> LegacyOutcomeHint:
    """Reduce an arbitrary legacy string to a bounded, untrusted enum hint."""

    if value is None or not value.strip():
        return LegacyOutcomeHint.NONE
    normalized = value.strip().lower()
    if normalized == "success":
        return LegacyOutcomeHint.SUCCESS
    if normalized in {"failure", "failed", "error"}:
        return LegacyOutcomeHint.FAILURE
    return LegacyOutcomeHint.OTHER


def _canonical_outcome(value: TaskOutcome | None) -> CanonicalTaskOutcome:
    mapping = {
        TaskOutcome.COMPLETED: CanonicalTaskOutcome.COMPLETED,
        TaskOutcome.COMPLETED_WITH_BUDGET_WARNING: (
            CanonicalTaskOutcome.COMPLETED_WITH_WARNING
        ),
        TaskOutcome.INTERRUPTED: CanonicalTaskOutcome.INTERRUPTED,
        TaskOutcome.FAILED: CanonicalTaskOutcome.FAILED,
        TaskOutcome.CANCELED: CanonicalTaskOutcome.CANCELED,
        None: CanonicalTaskOutcome.UNKNOWN,
    }
    return mapping[value]


def _approval_state(records: tuple[ApprovalRecord, ...]) -> ApprovalState:
    if not records:
        return ApprovalState.UNKNOWN
    statuses = {record.status for record in records}
    if ApprovalStatus.DENIED in statuses:
        return ApprovalState.DENIED
    if ApprovalStatus.EXPIRED in statuses:
        return ApprovalState.TIMED_OUT
    if ApprovalStatus.PENDING in statuses:
        return ApprovalState.PENDING
    if statuses == {ApprovalStatus.APPROVED}:
        return ApprovalState.APPROVED
    return ApprovalState.UNKNOWN


def _policy_result(decision: ToolPolicyDecision | None) -> PolicyResult:
    if decision is None:
        return PolicyResult.UNKNOWN
    if decision.allowed or decision.status == "waiting_approval":
        return PolicyResult.ALLOWED
    return PolicyResult.DENIED


def _tool_action_snapshot(action: ToolAction) -> ToolActionSnapshot:
    state_mapping = {
        ActionStatus.COMPLETED: ToolActionEndState.COMPLETED,
        ActionStatus.FAILED: ToolActionEndState.FAILED,
        ActionStatus.DENIED: ToolActionEndState.DENIED,
        ActionStatus.CANCELED: ToolActionEndState.CANCELED,
        ActionStatus.PROPOSED: ToolActionEndState.PENDING,
        ActionStatus.VALIDATED: ToolActionEndState.PENDING,
        ActionStatus.WAITING_APPROVAL: ToolActionEndState.PENDING,
        ActionStatus.RUNNING: ToolActionEndState.PENDING,
        ActionStatus.VERIFYING: ToolActionEndState.PENDING,
        ActionStatus.VERIFIED: ToolActionEndState.PENDING,
    }
    verification_mapping = {
        RuntimeVerificationStatus.PENDING: VerificationState.PENDING,
        RuntimeVerificationStatus.PASSED: VerificationState.PASSED,
        RuntimeVerificationStatus.FAILED: VerificationState.FAILED,
        RuntimeVerificationStatus.UNKNOWN: VerificationState.UNKNOWN,
    }
    return ToolActionSnapshot(
        action_id=action.action_id,
        state=state_mapping[action.status],
        verification_state=verification_mapping[action.verification_status],
        effect_known=action.effect_known,
    )


def _verification_state(
    actions: tuple[ToolActionSnapshot, ...],
) -> VerificationState:
    if not actions:
        return VerificationState.NOT_EVALUATED
    states = {action.verification_state for action in actions}
    if VerificationState.FAILED in states:
        return VerificationState.FAILED
    if all(
        action.state is ToolActionEndState.COMPLETED
        and action.verification_state is VerificationState.PASSED
        for action in actions
    ):
        return VerificationState.PASSED
    if VerificationState.UNKNOWN in states:
        return VerificationState.UNKNOWN
    return VerificationState.PENDING


def _browser_state(record: BrowserRecoveryRecord | None) -> BrowserRecoveryState:
    if record is None:
        return BrowserRecoveryState.NOT_APPLICABLE
    if record.reconnect_succeeded or record.control_restart_succeeded:
        return BrowserRecoveryState.RECOVERED
    return BrowserRecoveryState.FAILED


def _budget_state(usage: TaskUsage | None) -> BudgetState:
    if usage is None:
        return BudgetState.UNKNOWN
    if usage.hard_exceeded:
        return BudgetState.EXCEEDED
    if usage.warning:
        return BudgetState.WARNING
    return BudgetState.WITHIN_LIMITS


def _external_effect_state(
    actions: tuple[ToolActionSnapshot, ...],
) -> ExternalEffectState:
    if not actions:
        return ExternalEffectState.NONE
    if any(not action.effect_known for action in actions):
        return ExternalEffectState.UNKNOWN
    return ExternalEffectState.KNOWN


def snapshot_from_runtime(
    task: TaskRecord,
    *,
    trace_id: str,
    task_type: str,
    requested_goal: str,
    events: Iterable[TaskEvent] = (),
    tool_actions: Iterable[ToolAction] = (),
    approval_records: Iterable[ApprovalRecord] = (),
    policy_decision: ToolPolicyDecision | None = None,
    browser_recovery: BrowserRecoveryRecord | None = None,
    usage: TaskUsage | None = None,
    evidence_state: EvidenceState = EvidenceState.UNKNOWN,
    evidence_references: Iterable[EvidenceReference] = (),
    relevant_artifact_ids: Iterable[str] = (),
    warnings: Iterable[str] = (),
    verification_state: VerificationState | None = None,
    approval_state: ApprovalState | None = None,
    policy_result: PolicyResult | None = None,
    browser_recovery_state: BrowserRecoveryState | None = None,
    budget_state: BudgetState | None = None,
    external_effect_state: ExternalEffectState | None = None,
    legacy_trace_outcome: str | None = None,
    model_claimed_success: bool = False,
    feedback_score: float | None = None,
    judge_score: float | None = None,
    legacy_exit_code: int | None = None,
    legacy_http_status: int | None = None,
) -> EvaluationInput:
    """Adapt synthetic/current runtime value objects without opening stores.

    Callers must provide an already-redacted goal. Task descriptions, event
    payloads, tool outputs, chats, and browser content are never copied.
    Missing canonical facts remain explicit ``unknown``/``not_evaluated`` and
    therefore cannot create a successful evaluation.
    """

    runtime_events = tuple(events)
    action_snapshots = tuple(_tool_action_snapshot(action) for action in tool_actions)
    approvals = tuple(approval_records)
    state_history = tuple(
        TaskStateSnapshot(
            event_id=event.event_id,
            sequence=event.sequence,
            status_from=event.status_from,
            status_to=event.status_to,
            occurred_at=event.occurred_at,
        )
        for event in runtime_events
        if event.status_to is not None
    )
    artifact_ids = {artifact_id for artifact_id in relevant_artifact_ids if artifact_id}
    artifact_ids.update(
        event.artifact_id for event in runtime_events if event.artifact_id is not None
    )
    return normalize_snapshot(
        EvaluationInput(
            task_id=task.task_id,
            session_id=task.session_id,
            correlation_id=task.correlation_id,
            trace_id=trace_id,
            task_type=task_type,
            requested_goal=requested_goal,
            terminal_task_state=task.status,
            task_outcome=_canonical_outcome(task.outcome),
            state_history=state_history,
            verification_state=(
                verification_state or _verification_state(action_snapshots)
            ),
            approval_state=approval_state or _approval_state(approvals),
            policy_result=policy_result or _policy_result(policy_decision),
            tool_actions=action_snapshots,
            browser_recovery_state=(
                browser_recovery_state or _browser_state(browser_recovery)
            ),
            evidence_state=evidence_state,
            budget_state=budget_state or _budget_state(usage),
            user_canceled=(
                task.status.value == "canceled" or task.outcome is TaskOutcome.CANCELED
            ),
            turn_interrupted=task.outcome is TaskOutcome.INTERRUPTED,
            external_effect_state=(
                external_effect_state or _external_effect_state(action_snapshots)
            ),
            evidence_references=tuple(evidence_references),
            relevant_event_ids=tuple(event.event_id for event in runtime_events),
            relevant_artifact_ids=tuple(artifact_ids),
            warnings=tuple(warnings),
            legacy_hints=LegacyHints(
                trace_outcome=normalize_legacy_outcome(legacy_trace_outcome),
                model_claimed_success=model_claimed_success,
                feedback_score=feedback_score,
                judge_score=judge_score,
                exit_code=legacy_exit_code,
                http_status=legacy_http_status,
            ),
        )
    )


__all__ = [
    "canonical_json",
    "input_digest",
    "normalize_legacy_outcome",
    "normalize_snapshot",
    "sha256_digest",
    "snapshot_from_runtime",
]
