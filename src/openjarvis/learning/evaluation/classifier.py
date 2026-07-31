"""Deterministic, side-effect-free classification of evaluation snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openjarvis.learning.evaluation.evidence import has_complete_evidence
from openjarvis.learning.evaluation.models import (
    DEFAULT_EVALUATOR_ID,
    DEFAULT_EVALUATOR_VERSION,
    ApprovalState,
    BrowserRecoveryState,
    BudgetState,
    CanonicalTaskOutcome,
    ConfidenceBasis,
    ConfidenceLevel,
    EvaluationClass,
    EvaluationInput,
    EvidenceState,
    ExternalEffectState,
    FailureCategory,
    PolicyResult,
    ToolResultSummary,
    TraceEvaluation,
    VerificationState,
    new_evaluation_id,
    utc_now,
)
from openjarvis.learning.evaluation.normalization import (
    input_digest,
    normalize_snapshot,
    sha256_digest,
)
from openjarvis.tasks.types import TaskStatus

# This order is the public classifier contract. A more specific trusted cause
# always wins over generic failure indicators and legacy/model success hints.
CLASSIFICATION_PRIORITY = (
    "unsafe_request",
    "policy_denied",
    "user_canceled",
    "approval_denied",
    "approval_timeout",
    "budget_exceeded",
    "interrupted_without_verified_success",
    "unknown_external_effect",
    "verification_failed",
    "conflicting_evidence",
    "insufficient_evidence",
    "browser_failed",
    "tool_failed",
    "partial",
    "completed_with_warning",
    "completed",
    "unknown_failure",
)


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    evaluation_class: EvaluationClass
    failure_category: FailureCategory
    warnings: tuple[str, ...] = ()


class TraceClassifier:
    """Classify only canonical metadata; never invoke tools, stores, or models."""

    def __init__(
        self,
        *,
        evaluator_id: str = DEFAULT_EVALUATOR_ID,
        evaluator_version: str = DEFAULT_EVALUATOR_VERSION,
    ) -> None:
        self.evaluator_id = evaluator_id
        self.evaluator_version = evaluator_version

    def evaluate(
        self,
        snapshot: EvaluationInput,
        *,
        evaluation_id: str | None = None,
        created_at: datetime | None = None,
    ) -> TraceEvaluation:
        """Return a new immutable evaluation for the normalized snapshot."""

        normalized = normalize_snapshot(snapshot)
        digest = input_digest(normalized)
        summary = ToolResultSummary.from_actions(normalized.tool_actions)
        decision = self._classify(normalized, summary)
        confidence, confidence_basis = self._confidence(normalized, decision)
        warnings = tuple(sorted(set(normalized.warnings + decision.warnings)))
        semantic_payload = {
            "schema_version": "1.0",
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "task_id": normalized.task_id,
            "session_id": normalized.session_id,
            "correlation_id": normalized.correlation_id,
            "trace_id": normalized.trace_id,
            "task_type": normalized.task_type,
            "requested_goal": normalized.requested_goal,
            "terminal_task_state": normalized.terminal_task_state.value,
            "task_outcome": normalized.task_outcome.value,
            "evaluation_class": decision.evaluation_class.value,
            "verification_state": normalized.verification_state.value,
            "approval_state": normalized.approval_state.value,
            "policy_result": normalized.policy_result.value,
            "evidence_state": normalized.evidence_state.value,
            "tool_result_summary": summary.model_dump(mode="json"),
            "failure_category": decision.failure_category.value,
            "confidence": confidence.value,
            "confidence_basis": sorted(value.value for value in confidence_basis),
            "evidence_references": [
                reference.model_dump(mode="json")
                for reference in normalized.evidence_references
            ],
            "warnings": list(warnings),
            "input_digest": digest,
        }
        evaluation_hash = sha256_digest(semantic_payload)
        return TraceEvaluation(
            evaluation_id=evaluation_id or new_evaluation_id(),
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            task_id=normalized.task_id,
            session_id=normalized.session_id,
            correlation_id=normalized.correlation_id,
            trace_id=normalized.trace_id,
            task_type=normalized.task_type,
            requested_goal=normalized.requested_goal,
            terminal_task_state=normalized.terminal_task_state,
            task_outcome=normalized.task_outcome,
            evaluation_class=decision.evaluation_class,
            verification_state=normalized.verification_state,
            approval_state=normalized.approval_state,
            policy_result=normalized.policy_result,
            evidence_state=normalized.evidence_state,
            tool_result_summary=summary,
            failure_category=decision.failure_category,
            confidence=confidence,
            confidence_basis=confidence_basis,
            evidence_references=normalized.evidence_references,
            warnings=warnings,
            created_at=created_at or utc_now(),
            input_digest=digest,
            evaluation_hash=evaluation_hash,
        )

    @staticmethod
    def _is_verified_terminal_success(snapshot: EvaluationInput) -> bool:
        summary = ToolResultSummary.from_actions(snapshot.tool_actions)
        return all(
            (
                snapshot.terminal_task_state is TaskStatus.DONE,
                snapshot.task_outcome
                in {
                    CanonicalTaskOutcome.COMPLETED,
                    CanonicalTaskOutcome.COMPLETED_WITH_WARNING,
                },
                snapshot.verification_state is VerificationState.PASSED,
                snapshot.approval_state
                in {ApprovalState.APPROVED, ApprovalState.NOT_REQUIRED},
                snapshot.policy_result
                in {PolicyResult.ALLOWED, PolicyResult.NOT_REQUIRED},
                snapshot.evidence_state is EvidenceState.SUFFICIENT,
                snapshot.budget_state
                in {BudgetState.WITHIN_LIMITS, BudgetState.WARNING},
                snapshot.external_effect_state
                in {ExternalEffectState.NONE, ExternalEffectState.KNOWN},
                summary.failed == 0,
                summary.denied == 0,
                summary.canceled == 0,
                summary.pending == 0,
                summary.unknown == 0,
                summary.unknown_effects == 0,
            )
        )

    @classmethod
    def _classify(
        cls,
        snapshot: EvaluationInput,
        summary: ToolResultSummary,
    ) -> ClassificationDecision:
        # 1-2: security/policy causes outrank every execution symptom.
        if snapshot.policy_result is PolicyResult.UNSAFE:
            return ClassificationDecision(
                EvaluationClass.UNSAFE_REQUEST,
                FailureCategory.UNSAFE_REQUEST,
            )
        if snapshot.policy_result is PolicyResult.DENIED:
            return ClassificationDecision(
                EvaluationClass.POLICY_DENIED,
                FailureCategory.POLICY,
            )

        # 3-5: explicit human/lifecycle outcomes remain distinct.
        if snapshot.user_canceled or (
            snapshot.terminal_task_state is TaskStatus.CANCELED
            or snapshot.task_outcome is CanonicalTaskOutcome.CANCELED
        ):
            return ClassificationDecision(
                EvaluationClass.CANCELED,
                FailureCategory.CANCELED,
            )
        if snapshot.approval_state is ApprovalState.DENIED:
            return ClassificationDecision(
                EvaluationClass.APPROVAL_DENIED,
                FailureCategory.APPROVAL_DENIED,
            )
        if snapshot.approval_state is ApprovalState.TIMED_OUT:
            return ClassificationDecision(
                EvaluationClass.APPROVAL_TIMEOUT,
                FailureCategory.APPROVAL_TIMEOUT,
            )
        if snapshot.budget_state is BudgetState.EXCEEDED:
            return ClassificationDecision(
                EvaluationClass.BUDGET_EXCEEDED,
                FailureCategory.BUDGET,
            )

        verified_success = cls._is_verified_terminal_success(snapshot)
        if (
            snapshot.turn_interrupted
            or snapshot.task_outcome is CanonicalTaskOutcome.INTERRUPTED
        ) and not verified_success:
            return ClassificationDecision(
                EvaluationClass.INTERRUPTED,
                FailureCategory.INTERRUPTED,
            )

        # Unknown external effect can never be converted into success or retried.
        if (
            snapshot.external_effect_state is ExternalEffectState.UNKNOWN
            or summary.unknown_effects > 0
        ):
            return ClassificationDecision(
                EvaluationClass.UNKNOWN_FAILURE,
                FailureCategory.UNKNOWN_EFFECT,
                ("external_effect_unknown",),
            )

        # Canonical verification outranks exit code, HTTP status, model prose,
        # legacy trace outcomes, SkillExecutor booleans, and judge feedback.
        if snapshot.verification_state is VerificationState.FAILED:
            return ClassificationDecision(
                EvaluationClass.VERIFICATION_FAILED,
                FailureCategory.VERIFICATION,
            )
        if snapshot.evidence_state is EvidenceState.CONFLICTING:
            return ClassificationDecision(
                EvaluationClass.CONFLICTING_EVIDENCE,
                FailureCategory.EVIDENCE_CONFLICT,
            )
        if snapshot.evidence_state is EvidenceState.INSUFFICIENT:
            return ClassificationDecision(
                EvaluationClass.INSUFFICIENT_EVIDENCE,
                FailureCategory.EVIDENCE,
            )
        if snapshot.browser_recovery_state is BrowserRecoveryState.FAILED:
            return ClassificationDecision(
                EvaluationClass.BROWSER_FAILED,
                FailureCategory.BROWSER,
            )
        if summary.failed > 0 or summary.denied > 0:
            return ClassificationDecision(
                EvaluationClass.TOOL_FAILED,
                FailureCategory.TOOL,
            )
        if snapshot.task_outcome is CanonicalTaskOutcome.PARTIAL:
            return ClassificationDecision(
                EvaluationClass.PARTIAL,
                FailureCategory.PARTIAL,
            )

        if verified_success:
            warning = bool(snapshot.warnings) or (
                snapshot.task_outcome is CanonicalTaskOutcome.COMPLETED_WITH_WARNING
                or snapshot.budget_state is BudgetState.WARNING
            )
            if warning:
                return ClassificationDecision(
                    EvaluationClass.COMPLETED_WITH_WARNING,
                    FailureCategory.NONE,
                )
            return ClassificationDecision(
                EvaluationClass.COMPLETED,
                FailureCategory.NONE,
            )

        if snapshot.task_outcome in {
            CanonicalTaskOutcome.COMPLETED,
            CanonicalTaskOutcome.COMPLETED_WITH_WARNING,
        }:
            return ClassificationDecision(
                EvaluationClass.INSUFFICIENT_EVIDENCE,
                FailureCategory.EVIDENCE,
                ("completed_outcome_missing_canonical_verification",),
            )

        # No free-form legacy string or model assertion is consulted here.
        return ClassificationDecision(
            EvaluationClass.UNKNOWN_FAILURE,
            FailureCategory.UNKNOWN,
        )

    @staticmethod
    def _confidence(
        snapshot: EvaluationInput,
        decision: ClassificationDecision,
    ) -> tuple[ConfidenceLevel, tuple[ConfidenceBasis, ...]]:
        if snapshot.legacy_hints.has_hints():
            return (
                ConfidenceLevel.LOW,
                (
                    ConfidenceBasis.INCOMPLETE_CANONICAL_DATA,
                    ConfidenceBasis.LEGACY_HINTS_IGNORED,
                ),
            )
        if snapshot.evidence_state is EvidenceState.CONFLICTING:
            return (
                ConfidenceLevel.LOW,
                (ConfidenceBasis.CONFLICTING_CANONICAL_DATA,),
            )
        if decision.evaluation_class in {
            EvaluationClass.INSUFFICIENT_EVIDENCE,
            EvaluationClass.UNKNOWN_FAILURE,
        }:
            return (
                ConfidenceLevel.LOW,
                (ConfidenceBasis.INCOMPLETE_CANONICAL_DATA,),
            )
        if (
            snapshot.evidence_state is EvidenceState.SUFFICIENT
            and has_complete_evidence(
                decision.evaluation_class,
                snapshot.evidence_references,
            )
        ):
            return (
                ConfidenceLevel.HIGH,
                (
                    ConfidenceBasis.FULL_CANONICAL_EVIDENCE,
                    ConfidenceBasis.SPECIFIC_TERMINAL_CAUSE,
                ),
            )
        return (
            ConfidenceLevel.MEDIUM,
            (
                ConfidenceBasis.MISSING_NON_BLOCKING_DATA,
                ConfidenceBasis.SPECIFIC_TERMINAL_CAUSE,
            ),
        )


__all__ = [
    "CLASSIFICATION_PRIORITY",
    "ClassificationDecision",
    "TraceClassifier",
]
