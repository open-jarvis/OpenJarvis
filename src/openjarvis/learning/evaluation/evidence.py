"""Deterministic evidence requirements for trace evaluations."""

from __future__ import annotations

from openjarvis.learning.evaluation.models import (
    EvaluationClass,
    EvidenceReference,
    EvidenceType,
    EvidenceVerificationState,
    TrustedBoundary,
)

_REQUIRED_EVIDENCE: dict[EvaluationClass, frozenset[EvidenceType]] = {
    EvaluationClass.COMPLETED: frozenset(
        {
            EvidenceType.TASK_STATE,
            EvidenceType.TASK_OUTCOME,
            EvidenceType.VERIFICATION_RESULT,
            EvidenceType.POLICY_RESULT,
            EvidenceType.APPROVAL_RESULT,
            EvidenceType.BUDGET_RESULT,
        }
    ),
    EvaluationClass.COMPLETED_WITH_WARNING: frozenset(
        {
            EvidenceType.TASK_STATE,
            EvidenceType.TASK_OUTCOME,
            EvidenceType.VERIFICATION_RESULT,
            EvidenceType.POLICY_RESULT,
            EvidenceType.APPROVAL_RESULT,
            EvidenceType.BUDGET_RESULT,
        }
    ),
    EvaluationClass.PARTIAL: frozenset({EvidenceType.TASK_OUTCOME}),
    EvaluationClass.INTERRUPTED: frozenset({EvidenceType.TASK_OUTCOME}),
    EvaluationClass.CANCELED: frozenset({EvidenceType.USER_CANCEL}),
    EvaluationClass.POLICY_DENIED: frozenset({EvidenceType.POLICY_RESULT}),
    EvaluationClass.APPROVAL_DENIED: frozenset({EvidenceType.APPROVAL_RESULT}),
    EvaluationClass.APPROVAL_TIMEOUT: frozenset({EvidenceType.APPROVAL_RESULT}),
    EvaluationClass.VERIFICATION_FAILED: frozenset({EvidenceType.VERIFICATION_RESULT}),
    EvaluationClass.TOOL_FAILED: frozenset({EvidenceType.TOOL_RESULT}),
    EvaluationClass.BROWSER_FAILED: frozenset({EvidenceType.BROWSER_RECOVERY_RESULT}),
    EvaluationClass.BUDGET_EXCEEDED: frozenset({EvidenceType.BUDGET_RESULT}),
    EvaluationClass.UNSAFE_REQUEST: frozenset({EvidenceType.POLICY_RESULT}),
}


def required_evidence_types(
    evaluation_class: EvaluationClass,
) -> frozenset[EvidenceType]:
    """Return the canonical evidence types required for high confidence."""

    return _REQUIRED_EVIDENCE.get(evaluation_class, frozenset())


def verified_trusted_evidence_types(
    references: tuple[EvidenceReference, ...],
) -> frozenset[EvidenceType]:
    """Return evidence types verified inside a trusted runtime boundary."""

    trusted = {
        TrustedBoundary.CANONICAL_RUNTIME,
        TrustedBoundary.EXPLICIT_USER,
    }
    return frozenset(
        reference.evidence_type
        for reference in references
        if reference.verification_state is EvidenceVerificationState.VERIFIED
        and reference.trusted_boundary in trusted
    )


def has_complete_evidence(
    evaluation_class: EvaluationClass,
    references: tuple[EvidenceReference, ...],
) -> bool:
    """Check whether all class-specific evidence is verified and trusted."""

    required = required_evidence_types(evaluation_class)
    if not required:
        return False
    return required.issubset(verified_trusted_evidence_types(references))


__all__ = [
    "has_complete_evidence",
    "required_evidence_types",
    "verified_trusted_evidence_types",
]
