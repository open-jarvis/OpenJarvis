from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from openjarvis.learning.candidates import (
    CandidateExtractor,
    CandidateState,
    QuarantineReason,
)
from openjarvis.learning.lifecycle import (
    ActorType,
    QuarantineResolution,
    TransitionDeniedError,
    TransitionRequest,
)
from openjarvis.learning.lifecycle.service import CandidateLifecycleService
from openjarvis.learning.store import (
    ExpectedRevisionError,
    IdempotencyConflictError,
    LearningIntegrityError,
    LearningRepository,
    SQLiteLearningDatabase,
)

from .conftest import NOW, envelope, ingest, make_evaluation


def _seed_candidate(
    repository: LearningRepository,
    *,
    suffix: str = "a",
) -> str:
    evaluation = make_evaluation(
        evaluation_id=f"evaluation_{suffix}",
        task_id=f"task_{suffix}",
        session_id=f"session_{suffix}",
        trace_id=f"trace_{suffix}",
        task_type=f"synthetic.{suffix}",
    )
    result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    return (
        ingest(
            repository,
            evaluation,
            result,
            key=f"seed_{suffix}",
        )
        .candidates[0]
        .candidate_id
    )


def _request(
    candidate_id: str,
    *,
    expected_revision: int,
    target: CandidateState,
    key: str,
    reasons: tuple[QuarantineReason, ...] = (),
    resolutions: tuple[QuarantineResolution, ...] = (),
    actor: ActorType = ActorType.USER,
) -> TransitionRequest:
    return TransitionRequest(
        candidate_id=candidate_id,
        expected_revision=expected_revision,
        target_state=target,
        actor_type=actor,
        actor_id="actor_synthetic",
        reason=f"Synthetic transition to {target.value}",
        reason_code=f"transition_{target.value}",
        correlation_id=f"correlation_{key}",
        idempotency_key=key,
        quarantine_reasons=reasons,
        quarantine_resolution_records=resolutions,
    )


@pytest.mark.parametrize(
    "target",
    [
        CandidateState.UNDER_REVIEW,
        CandidateState.REJECTED,
        CandidateState.QUARANTINED,
    ],
)
def test_allowed_transition_from_proposed(
    repository: LearningRepository,
    target: CandidateState,
) -> None:
    candidate_id = _seed_candidate(repository, suffix=target.value)
    reasons = (
        (QuarantineReason.UNKNOWN_PROVENANCE,)
        if target is CandidateState.QUARANTINED
        else ()
    )
    outcome = repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=target,
            key=f"proposed_{target.value}",
            reasons=reasons,
        )
    )
    assert outcome.revision == 2
    assert repository.get_candidate_head(candidate_id).state is target


@pytest.mark.parametrize(
    "target",
    [CandidateState.REJECTED, CandidateState.QUARANTINED],
)
def test_allowed_transition_from_under_review(
    repository: LearningRepository,
    target: CandidateState,
) -> None:
    candidate_id = _seed_candidate(repository, suffix=f"review_{target.value}")
    repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.UNDER_REVIEW,
            key=f"start_{target.value}",
        )
    )
    reasons = (
        (QuarantineReason.UNKNOWN_PROVENANCE,)
        if target is CandidateState.QUARANTINED
        else ()
    )
    repository.transition(
        _request(
            candidate_id,
            expected_revision=2,
            target=target,
            key=f"finish_{target.value}",
            reasons=reasons,
        )
    )
    assert repository.get_candidate_head(candidate_id).state is target


def test_quarantine_requires_complete_resolution(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="resolution_required")
    repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.QUARANTINED,
            key="quarantine_required",
            reasons=(
                QuarantineReason.UNKNOWN_PROVENANCE,
                QuarantineReason.PROMPT_INJECTION,
            ),
        )
    )
    incomplete = QuarantineResolution(
        resolution_id="resolution_unknown",
        quarantine_reason=QuarantineReason.UNKNOWN_PROVENANCE,
        evidence_digest="a" * 64,
        summary="Canonical source was supplied",
    )
    with pytest.raises(TransitionDeniedError, match="every quarantine reason"):
        repository.transition(
            _request(
                candidate_id,
                expected_revision=2,
                target=CandidateState.UNDER_REVIEW,
                key="resolution_incomplete",
                resolutions=(incomplete,),
            )
        )
    assert (
        repository.get_candidate_head(candidate_id).state is CandidateState.QUARANTINED
    )


def test_complete_quarantine_resolution_enters_review(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="resolution_complete")
    reasons = (
        QuarantineReason.UNKNOWN_PROVENANCE,
        QuarantineReason.PROMPT_INJECTION,
    )
    repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.QUARANTINED,
            key="quarantine_complete",
            reasons=reasons,
        )
    )
    resolutions = tuple(
        QuarantineResolution(
            resolution_id=f"resolution_{reason.value}",
            quarantine_reason=reason,
            evidence_digest=("a" if index == 0 else "b") * 64,
            summary=f"Resolved synthetic reason {reason.value}",
        )
        for index, reason in enumerate(reasons)
    )
    outcome = repository.transition(
        _request(
            candidate_id,
            expected_revision=2,
            target=CandidateState.UNDER_REVIEW,
            key="resolution_complete",
            resolutions=resolutions,
        )
    )
    assert outcome.revision == 3
    head = repository.get_candidate_head(candidate_id)
    assert head.state is CandidateState.UNDER_REVIEW
    assert head.quarantine_reasons == ()


def test_manipulated_evaluation_quarantine_cannot_be_resolved(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="manipulated_resolution")
    repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.QUARANTINED,
            key="manipulated_quarantine",
            reasons=(QuarantineReason.MANIPULATED_EVALUATION,),
        )
    )
    resolution = QuarantineResolution(
        resolution_id="resolution_manipulated",
        quarantine_reason=QuarantineReason.MANIPULATED_EVALUATION,
        evidence_digest="a" * 64,
        summary="Synthetic replacement was requested",
    )
    with pytest.raises(TransitionDeniedError, match="cannot be resolved"):
        repository.transition(
            _request(
                candidate_id,
                expected_revision=2,
                target=CandidateState.UNDER_REVIEW,
                key="manipulated_resolution",
                resolutions=(resolution,),
            )
        )


def test_rejected_is_terminal(repository: LearningRepository) -> None:
    candidate_id = _seed_candidate(repository, suffix="terminal")
    repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.REJECTED,
            key="reject_terminal",
        )
    )
    with pytest.raises(TransitionDeniedError):
        repository.transition(
            _request(
                candidate_id,
                expected_revision=2,
                target=CandidateState.UNDER_REVIEW,
                key="terminal_escape",
            )
        )


def test_same_transition_idempotency_key_creates_one_revision(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="transition_idempotent")
    request = _request(
        candidate_id,
        expected_revision=1,
        target=CandidateState.UNDER_REVIEW,
        key="transition_replay",
    )
    first = repository.transition(request)
    second = repository.transition(request)
    assert second.idempotent is True
    assert second.transition.transition_id == first.transition.transition_id
    assert len(repository.candidate_history(candidate_id)) == 2
    assert len(repository.transition_history(candidate_id)) == 1


def test_transition_key_with_other_payload_is_rejected(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="transition_conflict")
    repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.UNDER_REVIEW,
            key="transition_key_conflict",
        )
    )
    with pytest.raises(IdempotencyConflictError):
        repository.transition(
            _request(
                candidate_id,
                expected_revision=1,
                target=CandidateState.REJECTED,
                key="transition_key_conflict",
            )
        )


def test_expected_revision_is_required_by_compare_and_swap(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="expected_revision")
    with pytest.raises(ExpectedRevisionError):
        repository.transition(
            _request(
                candidate_id,
                expected_revision=2,
                target=CandidateState.UNDER_REVIEW,
                key="wrong_expected_revision",
            )
        )


def test_two_concurrent_transitions_only_one_wins(
    database_path: Path,
) -> None:
    seed_repository = LearningRepository(SQLiteLearningDatabase(database_path))
    seed_repository.initialize()
    candidate_id = _seed_candidate(seed_repository, suffix="concurrent")
    barrier = Barrier(2)

    def attempt(index: int) -> str:
        repository = LearningRepository(SQLiteLearningDatabase(database_path))
        barrier.wait()
        try:
            repository.transition(
                _request(
                    candidate_id,
                    expected_revision=1,
                    target=CandidateState.UNDER_REVIEW,
                    key=f"concurrent_{index}",
                )
            )
        except ExpectedRevisionError:
            return "conflict"
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(attempt, range(2)))
    assert sorted(results) == ["conflict", "success"]
    restarted = LearningRepository(SQLiteLearningDatabase(database_path))
    assert restarted.get_candidate_head(candidate_id).revision == 2
    assert len(restarted.transition_history(candidate_id)) == 1


@pytest.mark.parametrize(
    "forbidden_actor",
    ["model", "webpage", "document", "imported_skill", "optimizer"],
)
def test_untrusted_actor_types_are_rejected(forbidden_actor: str) -> None:
    with pytest.raises(ValidationError):
        TransitionRequest(
            candidate_id="candidate_synthetic",
            expected_revision=1,
            target_state=CandidateState.UNDER_REVIEW,
            actor_type=forbidden_actor,
            actor_id="actor_synthetic",
            reason="Synthetic review request",
            reason_code="review_requested",
            correlation_id="correlation_actor",
            idempotency_key="idempotency_actor",
        )


def test_lifecycle_service_uses_repository_transaction(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="service")
    service = CandidateLifecycleService(repository)
    outcome = service.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.UNDER_REVIEW,
            key="service_transition",
        )
    )
    assert outcome.revision == 2


def test_transition_failure_rolls_back_revision_and_event(
    repository: LearningRepository,
    monkeypatch,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="transition_rollback")
    original = repository._append_event

    def fail_review_event(*args: object, **kwargs: object):
        if kwargs.get("event_type").value == "candidate.review_started":
            raise RuntimeError("synthetic transition crash")
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "_append_event", fail_review_event)
    with pytest.raises(RuntimeError, match="synthetic transition crash"):
        repository.transition(
            _request(
                candidate_id,
                expected_revision=1,
                target=CandidateState.UNDER_REVIEW,
                key="transition_rollback",
            )
        )
    assert repository.get_candidate_head(candidate_id).revision == 1
    assert len(repository.candidate_history(candidate_id)) == 1
    assert repository.transition_history(candidate_id) == ()


def test_restart_preserves_quarantine_and_transition_history(
    database_path: Path,
) -> None:
    first = LearningRepository(SQLiteLearningDatabase(database_path))
    first.initialize()
    candidate_id = _seed_candidate(first, suffix="restart_quarantine")
    first.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.QUARANTINED,
            key="restart_quarantine",
            reasons=(QuarantineReason.UNKNOWN_PROVENANCE,),
        )
    )
    restarted = LearningRepository(SQLiteLearningDatabase(database_path))
    assert (
        restarted.get_candidate_head(candidate_id).state is CandidateState.QUARANTINED
    )
    assert len(restarted.transition_history(candidate_id)) == 1


def test_tampered_transition_hash_is_detected(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="tamper_transition")
    outcome = repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.UNDER_REVIEW,
            key="tamper_transition",
        )
    )
    with repository.database.transaction() as connection:
        connection.execute(
            """
            UPDATE candidate_transition_events SET payload_json = ?
            WHERE transition_id = ?
            """,
            ("{}", outcome.transition.transition_id),
        )
    with pytest.raises(LearningIntegrityError, match="transition integrity"):
        repository.transition_history(candidate_id)


def test_review_revision_without_transition_is_detected(
    repository: LearningRepository,
) -> None:
    candidate_id = _seed_candidate(repository, suffix="missing_transition")
    outcome = repository.transition(
        _request(
            candidate_id,
            expected_revision=1,
            target=CandidateState.UNDER_REVIEW,
            key="missing_transition",
        )
    )
    with repository.database.transaction() as connection:
        connection.execute(
            "DELETE FROM candidate_transition_events WHERE transition_id = ?",
            (outcome.transition.transition_id,),
        )
    with pytest.raises(LearningIntegrityError, match="transition is missing"):
        repository.get_candidate_revision(candidate_id, 2)
