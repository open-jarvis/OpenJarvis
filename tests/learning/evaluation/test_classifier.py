from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from openjarvis.learning.evaluation import (
    CLASSIFICATION_PRIORITY,
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
    LegacyHints,
    LegacyOutcomeHint,
    PolicyResult,
    ToolActionEndState,
    ToolActionSnapshot,
    TraceClassifier,
    VerificationState,
)
from openjarvis.tasks.types import TaskStatus

from .conftest import NOW, replace_snapshot


def test_classification_priority_is_an_explicit_contract() -> None:
    assert CLASSIFICATION_PRIORITY == (
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


def test_verified_completed_is_completed(
    completed_snapshot: EvaluationInput,
) -> None:
    evaluation = TraceClassifier().evaluate(completed_snapshot)

    assert evaluation.evaluation_class is EvaluationClass.COMPLETED
    assert evaluation.failure_category is FailureCategory.NONE
    assert evaluation.confidence is ConfidenceLevel.HIGH
    assert ConfidenceBasis.FULL_CANONICAL_EVIDENCE in evaluation.confidence_basis


def test_completed_with_warning(
    completed_snapshot: EvaluationInput,
) -> None:
    snapshot = replace_snapshot(
        completed_snapshot,
        task_outcome=CanonicalTaskOutcome.COMPLETED_WITH_WARNING,
        warnings=("synthetic_non_blocking_warning",),
    )

    evaluation = TraceClassifier().evaluate(snapshot)

    assert evaluation.evaluation_class is EvaluationClass.COMPLETED_WITH_WARNING
    assert evaluation.warnings == ("synthetic_non_blocking_warning",)


@pytest.mark.parametrize(
    ("changes", "expected", "failure"),
    [
        (
            {"task_outcome": CanonicalTaskOutcome.PARTIAL},
            EvaluationClass.PARTIAL,
            FailureCategory.PARTIAL,
        ),
        (
            {
                "terminal_task_state": TaskStatus.CANCELED,
                "task_outcome": CanonicalTaskOutcome.CANCELED,
                "user_canceled": True,
            },
            EvaluationClass.CANCELED,
            FailureCategory.CANCELED,
        ),
        (
            {
                "terminal_task_state": TaskStatus.FAILED,
                "task_outcome": CanonicalTaskOutcome.INTERRUPTED,
                "turn_interrupted": True,
            },
            EvaluationClass.INTERRUPTED,
            FailureCategory.INTERRUPTED,
        ),
        (
            {"policy_result": PolicyResult.DENIED},
            EvaluationClass.POLICY_DENIED,
            FailureCategory.POLICY,
        ),
        (
            {"approval_state": ApprovalState.DENIED},
            EvaluationClass.APPROVAL_DENIED,
            FailureCategory.APPROVAL_DENIED,
        ),
        (
            {"approval_state": ApprovalState.TIMED_OUT},
            EvaluationClass.APPROVAL_TIMEOUT,
            FailureCategory.APPROVAL_TIMEOUT,
        ),
        (
            {"verification_state": VerificationState.FAILED},
            EvaluationClass.VERIFICATION_FAILED,
            FailureCategory.VERIFICATION,
        ),
        (
            {"browser_recovery_state": BrowserRecoveryState.FAILED},
            EvaluationClass.BROWSER_FAILED,
            FailureCategory.BROWSER,
        ),
        (
            {"evidence_state": EvidenceState.INSUFFICIENT},
            EvaluationClass.INSUFFICIENT_EVIDENCE,
            FailureCategory.EVIDENCE,
        ),
        (
            {"evidence_state": EvidenceState.CONFLICTING},
            EvaluationClass.CONFLICTING_EVIDENCE,
            FailureCategory.EVIDENCE_CONFLICT,
        ),
        (
            {"budget_state": BudgetState.EXCEEDED},
            EvaluationClass.BUDGET_EXCEEDED,
            FailureCategory.BUDGET,
        ),
        (
            {"policy_result": PolicyResult.UNSAFE},
            EvaluationClass.UNSAFE_REQUEST,
            FailureCategory.UNSAFE_REQUEST,
        ),
    ],
)
def test_specific_canonical_outcomes(
    completed_snapshot: EvaluationInput,
    changes: dict[str, object],
    expected: EvaluationClass,
    failure: FailureCategory,
) -> None:
    evaluation = TraceClassifier().evaluate(
        replace_snapshot(completed_snapshot, **changes)
    )

    assert evaluation.evaluation_class is expected
    assert evaluation.failure_category is failure


def test_tool_failure_is_used_only_without_more_specific_cause(
    completed_snapshot: EvaluationInput,
) -> None:
    failed_action = ToolActionSnapshot(
        action_id="action_failed",
        state=ToolActionEndState.FAILED,
        verification_state=VerificationState.NOT_EVALUATED,
        effect_known=True,
    )
    snapshot = replace_snapshot(
        completed_snapshot,
        terminal_task_state=TaskStatus.FAILED,
        task_outcome=CanonicalTaskOutcome.FAILED,
        verification_state=VerificationState.NOT_REQUIRED,
        tool_actions=(failed_action,),
        external_effect_state=ExternalEffectState.KNOWN,
    )

    evaluation = TraceClassifier().evaluate(snapshot)

    assert evaluation.evaluation_class is EvaluationClass.TOOL_FAILED


def test_unknown_combination_is_unknown_failure(
    completed_snapshot: EvaluationInput,
) -> None:
    snapshot = replace_snapshot(
        completed_snapshot,
        terminal_task_state=TaskStatus.FAILED,
        task_outcome=CanonicalTaskOutcome.FAILED,
        verification_state=VerificationState.NOT_REQUIRED,
    )

    evaluation = TraceClassifier().evaluate(snapshot)

    assert evaluation.evaluation_class is EvaluationClass.UNKNOWN_FAILURE
    assert evaluation.confidence is ConfidenceLevel.LOW


def test_turn_interrupt_does_not_replace_verified_terminal_success(
    completed_snapshot: EvaluationInput,
) -> None:
    snapshot = replace_snapshot(completed_snapshot, turn_interrupted=True)

    assert (
        TraceClassifier().evaluate(snapshot).evaluation_class
        is EvaluationClass.COMPLETED
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"verification_state": VerificationState.NOT_EVALUATED},
        {"approval_state": ApprovalState.PENDING},
        {"policy_result": PolicyResult.UNKNOWN},
        {"budget_state": BudgetState.UNKNOWN},
    ],
)
def test_incomplete_completed_outcome_is_not_success(
    completed_snapshot: EvaluationInput,
    changes: dict[str, object],
) -> None:
    evaluation = TraceClassifier().evaluate(
        replace_snapshot(completed_snapshot, **changes)
    )

    assert evaluation.evaluation_class is EvaluationClass.INSUFFICIENT_EVIDENCE


def test_unknown_external_effect_prevents_completed(
    completed_snapshot: EvaluationInput,
) -> None:
    evaluation = TraceClassifier().evaluate(
        replace_snapshot(
            completed_snapshot,
            external_effect_state=ExternalEffectState.UNKNOWN,
        )
    )

    assert evaluation.evaluation_class is EvaluationClass.UNKNOWN_FAILURE
    assert evaluation.failure_category is FailureCategory.UNKNOWN_EFFECT


def test_done_without_completed_outcome_is_not_success(
    completed_snapshot: EvaluationInput,
) -> None:
    evaluation = TraceClassifier().evaluate(
        replace_snapshot(
            completed_snapshot,
            task_outcome=CanonicalTaskOutcome.UNKNOWN,
        )
    )

    assert evaluation.evaluation_class is EvaluationClass.UNKNOWN_FAILURE


@pytest.mark.parametrize(
    "legacy_hints",
    [
        LegacyHints(model_claimed_success=True),
        LegacyHints(trace_outcome=LegacyOutcomeHint.SUCCESS),
        LegacyHints(exit_code=0),
        LegacyHints(http_status=200),
        LegacyHints(skill_reported_success=True),
        LegacyHints(feedback_score=1.0),
        LegacyHints(judge_score=1.0),
        LegacyHints(teacher_recommended_success=True),
    ],
)
def test_legacy_or_model_success_hint_cannot_create_success(
    completed_snapshot: EvaluationInput,
    legacy_hints: LegacyHints,
) -> None:
    snapshot = replace_snapshot(
        completed_snapshot,
        terminal_task_state=TaskStatus.FAILED,
        task_outcome=CanonicalTaskOutcome.UNKNOWN,
        verification_state=VerificationState.NOT_EVALUATED,
        evidence_state=EvidenceState.UNKNOWN,
        legacy_hints=legacy_hints,
    )

    evaluation = TraceClassifier().evaluate(snapshot)

    assert evaluation.evaluation_class is EvaluationClass.UNKNOWN_FAILURE
    assert evaluation.confidence is ConfidenceLevel.LOW
    assert ConfidenceBasis.LEGACY_HINTS_IGNORED in evaluation.confidence_basis


def test_legacy_hints_do_not_change_a_canonical_class(
    completed_snapshot: EvaluationInput,
) -> None:
    canonical = TraceClassifier().evaluate(completed_snapshot)
    with_legacy = TraceClassifier().evaluate(
        replace_snapshot(
            completed_snapshot,
            legacy_hints=LegacyHints(
                trace_outcome=LegacyOutcomeHint.SUCCESS,
                model_claimed_success=True,
                feedback_score=1.0,
            ),
        )
    )

    assert canonical.evaluation_class is EvaluationClass.COMPLETED
    assert with_legacy.evaluation_class is canonical.evaluation_class
    assert with_legacy.confidence is ConfidenceLevel.LOW


def test_zero_exit_and_http_200_tool_metadata_are_not_verification(
    completed_snapshot: EvaluationInput,
) -> None:
    action = ToolActionSnapshot(
        action_id="action_unverified",
        state=ToolActionEndState.PENDING,
        verification_state=VerificationState.NOT_EVALUATED,
        effect_known=True,
        exit_code=0,
        http_status=200,
    )
    snapshot = replace_snapshot(
        completed_snapshot,
        verification_state=VerificationState.NOT_EVALUATED,
        tool_actions=(action,),
        external_effect_state=ExternalEffectState.KNOWN,
    )

    evaluation = TraceClassifier().evaluate(snapshot)

    assert evaluation.evaluation_class is EvaluationClass.INSUFFICIENT_EVIDENCE
    assert evaluation.tool_result_summary.zero_exit_codes == 1
    assert evaluation.tool_result_summary.http_2xx == 1


def test_verification_failure_outranks_success_claims(
    completed_snapshot: EvaluationInput,
) -> None:
    snapshot = replace_snapshot(
        completed_snapshot,
        verification_state=VerificationState.FAILED,
        legacy_hints=LegacyHints(
            trace_outcome=LegacyOutcomeHint.SUCCESS,
            model_claimed_success=True,
            exit_code=0,
            http_status=200,
        ),
    )

    assert (
        TraceClassifier().evaluate(snapshot).evaluation_class
        is EvaluationClass.VERIFICATION_FAILED
    )


def test_policy_denial_outranks_tool_failure(
    completed_snapshot: EvaluationInput,
) -> None:
    action = ToolActionSnapshot(
        action_id="action_failed",
        state=ToolActionEndState.FAILED,
        verification_state=VerificationState.FAILED,
        effect_known=True,
    )
    snapshot = replace_snapshot(
        completed_snapshot,
        policy_result=PolicyResult.DENIED,
        verification_state=VerificationState.FAILED,
        tool_actions=(action,),
    )

    assert (
        TraceClassifier().evaluate(snapshot).evaluation_class
        is EvaluationClass.POLICY_DENIED
    )


def test_user_cancel_outranks_tool_failure(
    completed_snapshot: EvaluationInput,
) -> None:
    action = ToolActionSnapshot(
        action_id="action_failed",
        state=ToolActionEndState.FAILED,
        verification_state=VerificationState.FAILED,
        effect_known=True,
    )
    snapshot = replace_snapshot(
        completed_snapshot,
        terminal_task_state=TaskStatus.CANCELED,
        task_outcome=CanonicalTaskOutcome.CANCELED,
        user_canceled=True,
        tool_actions=(action,),
    )

    assert (
        TraceClassifier().evaluate(snapshot).evaluation_class
        is EvaluationClass.CANCELED
    )


def test_same_input_in_separate_instances_has_same_semantic_hash(
    completed_snapshot: EvaluationInput,
) -> None:
    first = TraceClassifier().evaluate(
        completed_snapshot,
        created_at=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )
    second = TraceClassifier().evaluate(
        completed_snapshot,
        created_at=datetime(2026, 7, 31, 12, 1, tzinfo=timezone.utc),
    )

    assert first.evaluation_id != second.evaluation_id
    assert first.created_at != second.created_at
    assert first.input_digest == second.input_digest
    assert first.evaluation_hash == second.evaluation_hash


def test_different_evaluator_version_creates_separate_evaluation(
    completed_snapshot: EvaluationInput,
) -> None:
    first = TraceClassifier(evaluator_version="1.0.0").evaluate(completed_snapshot)
    second = TraceClassifier(evaluator_version="1.1.0").evaluate(completed_snapshot)

    assert first.evaluation_id != second.evaluation_id
    assert first.input_digest == second.input_digest
    assert first.evaluation_hash != second.evaluation_hash


def test_evidence_order_does_not_change_hash(
    completed_snapshot: EvaluationInput,
) -> None:
    reversed_snapshot = replace_snapshot(
        completed_snapshot,
        evidence_references=tuple(reversed(completed_snapshot.evidence_references)),
    )
    first = TraceClassifier().evaluate(completed_snapshot)
    second = TraceClassifier().evaluate(reversed_snapshot)

    assert first.input_digest == second.input_digest
    assert first.evaluation_hash == second.evaluation_hash


def test_current_time_is_excluded_from_evaluation_hash(
    completed_snapshot: EvaluationInput,
) -> None:
    classifier = TraceClassifier()
    first = classifier.evaluate(completed_snapshot, created_at=NOW)
    second = classifier.evaluate(
        completed_snapshot,
        created_at=NOW + timedelta(days=1),
    )

    assert first.evaluation_hash == second.evaluation_hash
