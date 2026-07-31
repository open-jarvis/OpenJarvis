from __future__ import annotations

from datetime import timedelta

import pytest

from openjarvis.learning.candidates import (
    CandidateExtractor,
    CandidateState,
    CandidateType,
    CorrectionFeedbackContent,
    EvaluationEnvelope,
    EvaluationLineage,
    ExplicitFeedbackRecord,
    FactContent,
    FactFeedbackContent,
    FactValidity,
    FeedbackType,
    PreferenceContent,
    PreferenceFeedbackContent,
    QuarantineReason,
    UserCorrectionContent,
)
from openjarvis.learning.evaluation import (
    ApprovalState,
    EvaluationClass,
    PolicyResult,
    TraceEvaluation,
)

from .conftest import NOW, digest, envelope, make_evaluation


def _extract(*evaluations: TraceEvaluation):
    return CandidateExtractor().extract(
        tuple(envelope(evaluation) for evaluation in evaluations),
        created_at=NOW,
    )


def _feedback(
    *,
    feedback_id: str,
    feedback_type: FeedbackType,
    content: object,
    group: str | None = None,
) -> ExplicitFeedbackRecord:
    return ExplicitFeedbackRecord(
        feedback_id=feedback_id,
        feedback_type=feedback_type,
        user_source_id="user_synthetic",
        feedback_group_id=group or feedback_id,
        project="project_a",
        content=content,
        source_digest=digest(feedback_id),
        created_at=NOW,
    )


def test_verified_completed_proposes_success(completed_evaluation) -> None:
    result = _extract(completed_evaluation)
    candidate = result.candidates[0]
    assert candidate.candidate_type is CandidateType.SUCCESSFUL_SOLUTION
    assert candidate.state is CandidateState.PROPOSED
    assert candidate.required_review is True
    assert candidate.source_evidence_ids


def test_completed_with_warning_retains_warning_metadata() -> None:
    evaluation = make_evaluation(
        evaluation_class=EvaluationClass.COMPLETED_WITH_WARNING,
        warnings=("synthetic budget warning",),
    )
    candidate = _extract(evaluation).candidates[0]
    assert "synthetic budget warning" in candidate.structured_content.limitations


@pytest.mark.parametrize(
    "evaluation_class,overrides",
    [
        (EvaluationClass.PARTIAL, {}),
        (EvaluationClass.CANCELED, {}),
        (EvaluationClass.INTERRUPTED, {}),
        (EvaluationClass.POLICY_DENIED, {"policy_result": PolicyResult.DENIED}),
        (
            EvaluationClass.APPROVAL_DENIED,
            {"approval_state": ApprovalState.DENIED},
        ),
        (EvaluationClass.INSUFFICIENT_EVIDENCE, {}),
        (EvaluationClass.UNKNOWN_FAILURE, {}),
    ],
)
def test_conservative_classes_do_not_create_technical_candidates(
    evaluation_class: EvaluationClass,
    overrides: dict[str, object],
) -> None:
    result = _extract(make_evaluation(evaluation_class=evaluation_class, **overrides))
    assert result.candidates == ()
    assert result.warnings


@pytest.mark.parametrize(
    "evaluation_class",
    [
        EvaluationClass.VERIFICATION_FAILED,
        EvaluationClass.TOOL_FAILED,
        EvaluationClass.BROWSER_FAILED,
    ],
)
def test_specific_technical_failure_creates_pattern(
    evaluation_class: EvaluationClass,
) -> None:
    candidate = _extract(make_evaluation(evaluation_class=evaluation_class)).candidates[
        0
    ]
    assert candidate.candidate_type is CandidateType.FAILURE_PATTERN
    assert candidate.state is CandidateState.PROPOSED
    assert candidate.structured_content.task_type == "synthetic.unit"


def test_conflicting_evidence_is_quarantined() -> None:
    candidate = _extract(
        make_evaluation(evaluation_class=EvaluationClass.CONFLICTING_EVIDENCE)
    ).candidates[0]
    assert candidate.state is CandidateState.QUARANTINED
    assert QuarantineReason.CONFLICTING_EVIDENCE in candidate.quarantine_reasons


def test_task_success_does_not_infer_fact_or_preference(completed_evaluation) -> None:
    types = {item.candidate_type for item in _extract(completed_evaluation).candidates}
    assert CandidateType.FACT not in types
    assert CandidateType.PREFERENCE not in types


def test_explicit_fact_confirmation_creates_fact() -> None:
    content = FactFeedbackContent(
        fact=FactContent(
            subject="synthetic user",
            predicate="timezone",
            value="Europe Vienna",
            scope="user",
            validity=FactValidity.UNTIL_REVOKED,
            explicit_user_confirmation_required=False,
        )
    )
    record = _feedback(
        feedback_id="feedback_fact",
        feedback_type=FeedbackType.FACT_CONFIRMATION,
        content=content,
    )
    result = CandidateExtractor().extract(
        (), feedback_records=(record,), created_at=NOW
    )
    assert result.candidates[0].candidate_type is CandidateType.FACT
    assert result.candidates[0].independence_count == 1


def test_explicit_preference_creates_preference() -> None:
    record = _feedback(
        feedback_id="feedback_preference",
        feedback_type=FeedbackType.PREFERENCE,
        content=PreferenceFeedbackContent(
            preference=PreferenceContent(
                subject="synthetic user",
                preference="Prefer concise summaries",
                context="project reports",
            )
        ),
    )
    result = CandidateExtractor().extract(
        (), feedback_records=(record,), created_at=NOW
    )
    assert result.candidates[0].candidate_type is CandidateType.PREFERENCE


def test_explicit_correction_prioritizes_conflict(completed_evaluation) -> None:
    automatic = _extract(completed_evaluation).candidates[0]
    record = _feedback(
        feedback_id="feedback_correction",
        feedback_type=FeedbackType.USER_CORRECTION,
        content=CorrectionFeedbackContent(
            correction=UserCorrectionContent(
                target_reference=automatic.duplicate_signature,
                previous_value_digest=digest("previous"),
                corrected_value="The prior proposal is not valid",
                correction_scope="project",
            )
        ),
    )
    result = CandidateExtractor().extract(
        (envelope(completed_evaluation),),
        feedback_records=(record,),
        created_at=NOW,
    )
    assert len(result.conflict_links) == 1
    link = result.conflict_links[0]
    assert link.priority.value == "user_correction"
    preferred = next(
        item
        for item in result.candidates
        if item.candidate_id == link.preferred_candidate_id
    )
    assert preferred.candidate_type is CandidateType.USER_CORRECTION
    assert all(item.state is CandidateState.QUARANTINED for item in result.candidates)


def test_same_evaluation_has_same_duplicate_signature(completed_evaluation) -> None:
    first = _extract(completed_evaluation).candidates[0]
    second = _extract(completed_evaluation).candidates[0]
    assert first.duplicate_signature == second.duplicate_signature


def test_semantically_equal_evaluations_deduplicate() -> None:
    first = make_evaluation(evaluation_id="evaluation_a", task_id="task_a")
    second = make_evaluation(
        evaluation_id="evaluation_b",
        task_id="task_b",
        session_id="session_b",
        trace_id="trace_b",
    )
    result = _extract(first, second)
    assert len(result.candidates) == 1
    assert len(result.duplicate_links) == 1
    assert result.candidates[0].source_evaluation_ids == (
        "evaluation_a",
        "evaluation_b",
    )


def test_retry_does_not_raise_independence() -> None:
    original = make_evaluation(evaluation_id="evaluation_a", task_id="task_root")
    retry = make_evaluation(
        evaluation_id="evaluation_b",
        task_id="task_retry",
        session_id="session_b",
        trace_id="trace_b",
    )
    result = CandidateExtractor().extract(
        (
            envelope(original),
            envelope(
                retry,
                lineage=EvaluationLineage(retry_of_task_id="task_root"),
            ),
        ),
        created_at=NOW,
    )
    assert result.candidates[0].independence_count == 1


def test_second_evaluator_version_same_input_is_not_independent() -> None:
    input_hash = digest("shared input")
    first = make_evaluation(input_digest=input_hash, evaluation_id="evaluation_a")
    second = make_evaluation(
        input_digest=input_hash,
        evaluation_id="evaluation_b",
        evaluator_version="2.0.0",
    )
    assert _extract(first, second).candidates[0].independence_count == 1


def test_three_separate_tasks_are_independent() -> None:
    evaluations = tuple(
        make_evaluation(
            evaluation_id=f"evaluation_{index}",
            task_id=f"task_{index}",
            session_id=f"session_{index}",
            trace_id=f"trace_{index}",
        )
        for index in range(3)
    )
    assert _extract(*evaluations).candidates[0].independence_count == 3


def test_replayed_trace_is_not_independent() -> None:
    original = make_evaluation(evaluation_id="evaluation_a", trace_id="trace_root")
    replay = make_evaluation(
        evaluation_id="evaluation_b",
        task_id="task_replay",
        session_id="session_b",
        trace_id="trace_replay",
    )
    result = CandidateExtractor().extract(
        (
            envelope(original),
            envelope(
                replay,
                lineage=EvaluationLineage(replay_of_trace_id="trace_root"),
            ),
        ),
        created_at=NOW,
    )
    assert result.candidates[0].independence_count == 1


def test_resumed_thread_is_not_automatically_independent() -> None:
    first = make_evaluation(evaluation_id="evaluation_a")
    second = make_evaluation(
        evaluation_id="evaluation_b",
        task_id="task_b",
        session_id="session_b",
        trace_id="trace_b",
    )
    lineage = EvaluationLineage(thread_id="thread_shared")
    result = CandidateExtractor().extract(
        (envelope(first, lineage=lineage), envelope(second, lineage=lineage)),
        created_at=NOW,
    )
    assert result.candidates[0].independence_count == 1


def test_source_order_does_not_change_signature_or_run_hash() -> None:
    first = make_evaluation(evaluation_id="evaluation_a")
    second = make_evaluation(
        evaluation_id="evaluation_b",
        task_id="task_b",
        session_id="session_b",
        trace_id="trace_b",
    )
    left = _extract(first, second)
    right = _extract(second, first)
    assert (
        left.candidates[0].duplicate_signature
        == right.candidates[0].duplicate_signature
    )
    assert left.run_hash == right.run_hash


def test_timestamp_does_not_change_candidate_or_run_hash() -> None:
    first = make_evaluation(created_at=NOW)
    second = make_evaluation(created_at=NOW + timedelta(days=1))
    left = _extract(first)
    right = CandidateExtractor().extract(
        (envelope(second),),
        created_at=NOW + timedelta(days=2),
    )
    assert left.candidates[0].content_hash == right.candidates[0].content_hash
    assert left.run_hash == right.run_hash


def test_manipulated_evaluation_hash_is_rejected(completed_evaluation) -> None:
    payload = {
        field_name: getattr(completed_evaluation, field_name)
        for field_name in type(completed_evaluation).model_fields
    }
    payload["evaluation_hash"] = "f" * 64
    manipulated = TraceEvaluation.model_construct(**payload)
    with pytest.raises(ValueError, match="manipulated evaluation rejected"):
        CandidateExtractor().extract(
            (
                EvaluationEnvelope.model_construct(
                    evaluation=manipulated,
                    project="project_a",
                    scope="project",
                    lineage=EvaluationLineage(),
                ),
            ),
            created_at=NOW,
        )
