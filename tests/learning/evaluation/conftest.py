from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import pytest

from openjarvis.learning.evaluation import (
    ApprovalState,
    BrowserRecoveryState,
    BudgetState,
    CanonicalTaskOutcome,
    EvaluationInput,
    EvidenceReference,
    EvidenceSourceKind,
    EvidenceState,
    EvidenceType,
    EvidenceVerificationState,
    ExternalEffectState,
    PolicyResult,
    TrustedBoundary,
    VerificationState,
)
from openjarvis.tasks.types import TaskStatus

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def evidence(evidence_type: EvidenceType, index: int) -> EvidenceReference:
    source_mapping = {
        EvidenceType.TASK_STATE: EvidenceSourceKind.TASK_EVENT,
        EvidenceType.TASK_OUTCOME: EvidenceSourceKind.TASK_RECORD,
        EvidenceType.VERIFICATION_RESULT: EvidenceSourceKind.VERIFICATION_RECORD,
        EvidenceType.POLICY_RESULT: EvidenceSourceKind.POLICY_DECISION,
        EvidenceType.APPROVAL_RESULT: EvidenceSourceKind.APPROVAL_RECORD,
        EvidenceType.TOOL_RESULT: EvidenceSourceKind.TOOL_ACTION,
        EvidenceType.BROWSER_RECOVERY_RESULT: (EvidenceSourceKind.BROWSER_RECOVERY),
        EvidenceType.BUDGET_RESULT: EvidenceSourceKind.USAGE_RECORD,
        EvidenceType.USER_CANCEL: EvidenceSourceKind.USER_EVENT,
        EvidenceType.ARTIFACT_DIGEST: EvidenceSourceKind.ARTIFACT,
    }
    return EvidenceReference(
        evidence_id=f"evidence_{index}",
        evidence_type=evidence_type,
        source_kind=source_mapping[evidence_type],
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
    return tuple(
        evidence(evidence_type, index) for index, evidence_type in enumerate(types)
    )


def replace_snapshot(snapshot: EvaluationInput, **changes: Any) -> EvaluationInput:
    payload = snapshot.model_dump(mode="python", exclude_none=False)
    payload.update(changes)
    return EvaluationInput.model_validate(payload)


@pytest.fixture
def completed_snapshot() -> EvaluationInput:
    return EvaluationInput(
        task_id="task_synthetic",
        session_id="session_synthetic",
        correlation_id="correlation_synthetic",
        trace_id="trace_synthetic",
        task_type="synthetic.unit",
        requested_goal="Verify a synthetic task outcome",
        terminal_task_state=TaskStatus.DONE,
        task_outcome=CanonicalTaskOutcome.COMPLETED,
        verification_state=VerificationState.PASSED,
        approval_state=ApprovalState.NOT_REQUIRED,
        policy_result=PolicyResult.NOT_REQUIRED,
        browser_recovery_state=BrowserRecoveryState.NOT_APPLICABLE,
        evidence_state=EvidenceState.SUFFICIENT,
        budget_state=BudgetState.WITHIN_LIMITS,
        external_effect_state=ExternalEffectState.NONE,
        evidence_references=complete_evidence(),
        relevant_event_ids=("event_terminal",),
    )
