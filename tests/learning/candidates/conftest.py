from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import pytest

from openjarvis.learning.candidates import EvaluationEnvelope
from openjarvis.learning.evaluation import (
    ApprovalState,
    CanonicalTaskOutcome,
    ConfidenceBasis,
    ConfidenceLevel,
    EvaluationClass,
    EvidenceReference,
    EvidenceSourceKind,
    EvidenceState,
    EvidenceType,
    EvidenceVerificationState,
    FailureCategory,
    PolicyResult,
    ToolResultSummary,
    TraceEvaluation,
    TrustedBoundary,
    VerificationState,
)
from openjarvis.tasks.types import TaskStatus

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def evidence(evidence_type: EvidenceType, index: int) -> EvidenceReference:
    sources = {
        EvidenceType.TASK_STATE: EvidenceSourceKind.TASK_EVENT,
        EvidenceType.TASK_OUTCOME: EvidenceSourceKind.TASK_RECORD,
        EvidenceType.VERIFICATION_RESULT: EvidenceSourceKind.VERIFICATION_RECORD,
        EvidenceType.POLICY_RESULT: EvidenceSourceKind.POLICY_DECISION,
        EvidenceType.APPROVAL_RESULT: EvidenceSourceKind.APPROVAL_RECORD,
        EvidenceType.TOOL_RESULT: EvidenceSourceKind.TOOL_ACTION,
        EvidenceType.BROWSER_RECOVERY_RESULT: EvidenceSourceKind.BROWSER_RECOVERY,
        EvidenceType.BUDGET_RESULT: EvidenceSourceKind.USAGE_RECORD,
        EvidenceType.USER_CANCEL: EvidenceSourceKind.USER_EVENT,
        EvidenceType.ARTIFACT_DIGEST: EvidenceSourceKind.ARTIFACT,
    }
    return EvidenceReference(
        evidence_id=f"evidence_{index}",
        evidence_type=evidence_type,
        source_kind=sources[evidence_type],
        source_id=f"source_{index}",
        digest=digest(f"evidence:{index}:{evidence_type.value}"),
        verification_state=EvidenceVerificationState.VERIFIED,
        trusted_boundary=TrustedBoundary.CANONICAL_RUNTIME,
        created_at=NOW,
    )


def complete_evidence() -> tuple[EvidenceReference, ...]:
    types = (
        EvidenceType.TASK_STATE,
        EvidenceType.TASK_OUTCOME,
        EvidenceType.VERIFICATION_RESULT,
        EvidenceType.POLICY_RESULT,
        EvidenceType.APPROVAL_RESULT,
        EvidenceType.BUDGET_RESULT,
    )
    return tuple(evidence(value, index) for index, value in enumerate(types))


def make_evaluation(
    *,
    evaluation_id: str = "evaluation_a",
    evaluator_version: str = "1.0.0",
    task_id: str = "task_a",
    session_id: str = "session_a",
    trace_id: str = "trace_a",
    task_type: str = "synthetic.unit",
    evaluation_class: EvaluationClass = EvaluationClass.COMPLETED,
    input_digest: str | None = None,
    created_at: datetime = NOW,
    warnings: tuple[str, ...] = (),
    **overrides: Any,
) -> TraceEvaluation:
    failure_categories = {
        EvaluationClass.VERIFICATION_FAILED: FailureCategory.VERIFICATION,
        EvaluationClass.TOOL_FAILED: FailureCategory.TOOL,
        EvaluationClass.BROWSER_FAILED: FailureCategory.BROWSER,
        EvaluationClass.CONFLICTING_EVIDENCE: FailureCategory.EVIDENCE_CONFLICT,
        EvaluationClass.CANCELED: FailureCategory.CANCELED,
        EvaluationClass.INTERRUPTED: FailureCategory.INTERRUPTED,
        EvaluationClass.POLICY_DENIED: FailureCategory.POLICY,
        EvaluationClass.APPROVAL_DENIED: FailureCategory.APPROVAL_DENIED,
        EvaluationClass.PARTIAL: FailureCategory.PARTIAL,
        EvaluationClass.INSUFFICIENT_EVIDENCE: FailureCategory.EVIDENCE,
        EvaluationClass.UNKNOWN_FAILURE: FailureCategory.UNKNOWN,
    }
    payload: dict[str, Any] = {
        "evaluator_id": "synthetic_evaluator",
        "evaluator_version": evaluator_version,
        "task_id": task_id,
        "session_id": session_id,
        "correlation_id": f"correlation_{task_id}",
        "trace_id": trace_id,
        "task_type": task_type,
        "requested_goal": "Verify a synthetic task outcome",
        "terminal_task_state": (
            TaskStatus.DONE
            if evaluation_class
            in {
                EvaluationClass.COMPLETED,
                EvaluationClass.COMPLETED_WITH_WARNING,
            }
            else TaskStatus.FAILED
        ),
        "task_outcome": (
            CanonicalTaskOutcome.COMPLETED
            if evaluation_class is EvaluationClass.COMPLETED
            else CanonicalTaskOutcome.COMPLETED_WITH_WARNING
            if evaluation_class is EvaluationClass.COMPLETED_WITH_WARNING
            else CanonicalTaskOutcome.FAILED
        ),
        "evaluation_class": evaluation_class,
        "verification_state": (
            VerificationState.PASSED
            if evaluation_class
            in {
                EvaluationClass.COMPLETED,
                EvaluationClass.COMPLETED_WITH_WARNING,
            }
            else VerificationState.FAILED
            if evaluation_class is EvaluationClass.VERIFICATION_FAILED
            else VerificationState.NOT_REQUIRED
        ),
        "approval_state": ApprovalState.NOT_REQUIRED,
        "policy_result": PolicyResult.NOT_REQUIRED,
        "evidence_state": (
            EvidenceState.CONFLICTING
            if evaluation_class is EvaluationClass.CONFLICTING_EVIDENCE
            else EvidenceState.INSUFFICIENT
            if evaluation_class is EvaluationClass.INSUFFICIENT_EVIDENCE
            else EvidenceState.SUFFICIENT
        ),
        "tool_result_summary": ToolResultSummary(
            total=0,
            completed=0,
            failed=0,
            denied=0,
            canceled=0,
            pending=0,
            unknown=0,
            unknown_effects=0,
            zero_exit_codes=0,
            http_2xx=0,
        ),
        "failure_category": failure_categories.get(
            evaluation_class, FailureCategory.NONE
        ),
        "confidence": ConfidenceLevel.HIGH,
        "confidence_basis": (ConfidenceBasis.FULL_CANONICAL_EVIDENCE,),
        "evidence_references": complete_evidence(),
        "warnings": warnings,
        "input_digest": input_digest or digest(f"input:{task_id}:{trace_id}"),
    }
    payload.update(overrides)
    draft = TraceEvaluation.model_construct(
        evaluation_id=evaluation_id,
        created_at=created_at,
        evaluation_hash="0" * 64,
        **payload,
    )
    return TraceEvaluation(
        evaluation_id=evaluation_id,
        created_at=created_at,
        evaluation_hash=draft.recompute_hash(),
        **payload,
    )


def envelope(evaluation: TraceEvaluation, **kwargs: Any) -> EvaluationEnvelope:
    return EvaluationEnvelope(
        evaluation=evaluation,
        project=kwargs.pop("project", "project_a"),
        **kwargs,
    )


@pytest.fixture
def completed_evaluation() -> TraceEvaluation:
    return make_evaluation()
