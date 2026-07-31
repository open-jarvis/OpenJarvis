"""Hermetic verification lifecycle and explicit conflict-review tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.learning.candidates import (
    CandidateExtractor,
    CandidateState,
    ExplicitFeedbackRecord,
    FactContent,
    FactFeedbackContent,
    FactValidity,
    FeedbackType,
)
from openjarvis.learning.lifecycle import ActorType, TransitionDeniedError
from openjarvis.learning.lifecycle.conflicts import (
    ConflictResolutionDecision,
    ConflictResolutionRequest,
    ConflictReviewService,
)
from openjarvis.learning.lifecycle.models import TransitionRequest
from openjarvis.learning.skills import (
    REQUIRED_VERIFICATION_TYPES,
    FixtureClass,
    SkillManifest,
    SkillRegistryError,
    SkillTestCase,
    SkillTestResult,
    SkillTestRun,
    SkillTestType,
    SkillVerificationRecord,
    SkillVerificationService,
    VerificationStatus,
)
from openjarvis.learning.store import LearningRepository
from tests.learning.candidates.conftest import NOW, digest

from .test_manifest_legacy import valid_draft
from .test_registry import _register, _registry, _seed_reviewed_skill


def _registered_skill(path: Path):
    learning, registry = _registry(path)
    candidate_id = _seed_reviewed_skill(learning)
    manifest = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
        )
    )
    _register(registry, manifest, key="register_for_verification")
    return learning, registry, candidate_id, manifest


def _verification_record(
    *,
    candidate_id: str,
    candidate_revision: int,
    manifest: SkillManifest,
    failed_type: SkillTestType | None = None,
    activation_ready: bool = False,
) -> SkillVerificationRecord:
    cases = []
    results = []
    test_types = sorted(REQUIRED_VERIFICATION_TYPES, key=lambda item: item.value)
    if activation_ready:
        test_types.extend((SkillTestType.POSITIVE, SkillTestType.POSITIVE))
    for index, test_type in enumerate(test_types):
        fixture_id = (
            "fixture_holdout"
            if activation_ready and index == len(test_types) - 1
            else "fixture_development"
        )
        fixture_class = (
            FixtureClass.HOLDOUT
            if fixture_id == "fixture_holdout"
            else FixtureClass.DEVELOPMENT
        )
        test_id = f"test_{test_type.value}_{index}"
        evidence = digest(f"evidence_{test_id}")
        case = SkillTestCase.create(
            {
                "test_id": test_id,
                "test_version": 1,
                "test_type": test_type,
                "fixture_id": fixture_id,
                "fixture_class": fixture_class,
                "input_digest": digest(f"input_{test_id}"),
                "expected_evidence_digests": (evidence,),
                "expected_outcome": "completed",
                "created_at": NOW,
            }
        )
        passed = test_type is not failed_type
        result = SkillTestResult.create(
            {
                "result_id": f"result_{test_type.value}_{index}",
                "test_id": test_id,
                "test_version": 1,
                "test_type": test_type,
                "fixture_id": fixture_id,
                "passed": passed,
                "effect_known": True,
                "canonical_outcome": "completed" if passed else "failed",
                "evidence_digests": (evidence,),
                "duration_seconds": 0.01,
                "created_at": NOW,
            }
        )
        cases.append(case)
        results.append(result)
    run = SkillTestRun.create(
        {
            "run_id": (
                f"verification_run_{failed_type.value if failed_type else 'pass'}"
            ),
            "skill_id": manifest.skill_id,
            "semantic_version": manifest.semantic_version,
            "candidate_id": candidate_id,
            "candidate_revision": candidate_revision,
            "manifest_hash": manifest.content_hash,
            "hermetic": True,
            "test_cases": tuple(cases),
            "test_results": tuple(results),
            "created_at": NOW,
            "completed_at": NOW,
        }
    )
    fixture_ids = tuple(sorted({case.fixture_id for case in cases}))
    holdouts = tuple(
        sorted(
            {
                case.fixture_id
                for case in cases
                if case.fixture_class is FixtureClass.HOLDOUT
            }
        )
    )
    return SkillVerificationRecord.create(
        {
            "verification_id": (
                f"verification_{failed_type.value if failed_type else 'pass'}"
            ),
            "run": run,
            "status": (
                VerificationStatus.FAILED if failed_type else VerificationStatus.PASSED
            ),
            "required_test_types": tuple(REQUIRED_VERIFICATION_TYPES),
            "fixture_ids": fixture_ids,
            "holdout_fixture_ids": holdouts,
            "activation_ready": activation_ready,
            "evidence_digests": tuple(
                sorted(
                    {
                        evidence
                        for result in results
                        for evidence in result.evidence_digests
                    }
                )
            ),
            "created_at": NOW,
        }
    )


def _start_testing(service: SkillVerificationService, candidate_id: str):
    return service.start_testing(
        skill_id="skill.synthetic-read",
        semantic_version="1.0.0",
        expected_candidate_revision=2,
        expected_state_revision=1,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_verifier",
        correlation_id="correlation_verifier",
        idempotency_key="testing_start",
        evidence_reference_ids=("review_record",),
    )


def test_controlled_testing_and_verification_are_atomic(tmp_path: Path) -> None:
    learning, registry, candidate_id, manifest = _registered_skill(
        (tmp_path / "verification.sqlite3").resolve()
    )
    service = SkillVerificationService(registry)
    testing = _start_testing(service, candidate_id)
    assert testing.lifecycle_state.value == "testing"
    assert learning.get_candidate_head(candidate_id).state is CandidateState.TESTING

    record = _verification_record(
        candidate_id=candidate_id,
        candidate_revision=testing.candidate_revision,
        manifest=manifest,
    )
    outcome = service.verify(
        record,
        expected_state_revision=testing.state_revision,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_verifier",
        correlation_id="correlation_verifier",
        idempotency_key="verification_pass",
    )

    assert outcome.skill_head.lifecycle_state.value == "verified"
    assert learning.get_candidate_head(candidate_id).state is CandidateState.VERIFIED
    assert service.get_verification(record.run.run_id) == record
    replay = service.verify(
        record,
        expected_state_revision=testing.state_revision,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_verifier",
        correlation_id="correlation_verifier",
        idempotency_key="verification_pass",
    )
    assert replay.idempotent is True
    assert len(learning.candidate_history(candidate_id)) == 4


def test_verification_failure_never_promotes(tmp_path: Path) -> None:
    learning, registry, candidate_id, manifest = _registered_skill(
        (tmp_path / "verification.sqlite3").resolve()
    )
    service = SkillVerificationService(registry)
    testing = _start_testing(service, candidate_id)
    record = _verification_record(
        candidate_id=candidate_id,
        candidate_revision=testing.candidate_revision,
        manifest=manifest,
        failed_type=SkillTestType.POSTCONDITION,
    )
    outcome = service.verify(
        record,
        expected_state_revision=testing.state_revision,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_verifier",
        correlation_id="correlation_verifier",
        idempotency_key="verification_fail",
    )
    assert outcome.skill_head.lifecycle_state.value == "verification_failed"
    assert (
        learning.get_candidate_head(candidate_id).state
        is CandidateState.VERIFICATION_FAILED
    )
    with registry.database.reader() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM skill_promotion_records"
            ).fetchone()[0]
            == 0
        )

    reopened = service.reopen_after_failure(
        skill_id=manifest.skill_id,
        semantic_version=manifest.semantic_version,
        expected_candidate_revision=outcome.candidate_revision,
        expected_state_revision=outcome.skill_head.state_revision,
        reject=False,
        actor_type=ActorType.USER,
        actor_id="actor_reviewer",
        correlation_id="correlation_failure_review",
        idempotency_key="reopen_failed_verification",
        evidence_reference_ids=(record.verification_id,),
    )
    assert reopened.lifecycle_state.value == "draft"
    assert (
        learning.get_candidate_head(candidate_id).state is CandidateState.UNDER_REVIEW
    )


def test_direct_review_api_cannot_enter_privileged_skill_state(
    tmp_path: Path,
) -> None:
    learning, _, candidate_id, _ = _registered_skill(
        (tmp_path / "verification.sqlite3").resolve()
    )
    with pytest.raises(TransitionDeniedError, match="controlled skill service"):
        learning.transition(
            TransitionRequest(
                candidate_id=candidate_id,
                expected_revision=2,
                target_state=CandidateState.TESTING,
                actor_type=ActorType.USER,
                actor_id="actor_user",
                reason="Attempt direct testing.",
                reason_code="direct_testing",
                correlation_id="correlation_direct",
                idempotency_key="direct_testing",
                evidence_reference_ids=("untrusted_text",),
                skill_lifecycle_record_id="invented_record",
            )
        )
    assert (
        learning.get_candidate_head(candidate_id).state is CandidateState.UNDER_REVIEW
    )


def test_open_conflict_prevents_verification(tmp_path: Path, monkeypatch) -> None:
    _, registry, candidate_id, manifest = _registered_skill(
        (tmp_path / "verification.sqlite3").resolve()
    )
    service = SkillVerificationService(registry)
    testing = _start_testing(service, candidate_id)
    record = _verification_record(
        candidate_id=candidate_id,
        candidate_revision=testing.candidate_revision,
        manifest=manifest,
    )
    monkeypatch.setattr(registry.learning, "_has_open_conflict", lambda *_: True)
    with pytest.raises(SkillRegistryError, match="open conflict"):
        service.verify(
            record,
            expected_state_revision=testing.state_revision,
            actor_type=ActorType.DETERMINISTIC_TEST,
            actor_id="actor_verifier",
            correlation_id="correlation_verifier",
            idempotency_key="verification_conflict",
        )
    assert registry.get_head(manifest.skill_id, "1.0.0") == testing


def _fact_feedback(feedback_id: str, value: str) -> ExplicitFeedbackRecord:
    return ExplicitFeedbackRecord(
        feedback_id=feedback_id,
        feedback_type=FeedbackType.FACT_CONFIRMATION,
        user_source_id=f"user_{feedback_id}",
        feedback_group_id=f"group_{feedback_id}",
        project="project_a",
        content=FactFeedbackContent(
            fact=FactContent(
                subject="synthetic user",
                predicate="locale",
                value=value,
                scope="user",
                validity=FactValidity.UNTIL_REVOKED,
                explicit_user_confirmation_required=False,
            )
        ),
        source_digest=digest(feedback_id),
        created_at=NOW,
    )


def _ingest_feedback(
    repository: LearningRepository,
    record: ExplicitFeedbackRecord,
    *,
    key: str,
) -> str:
    result = CandidateExtractor().extract(
        (), feedback_records=(record,), created_at=NOW
    )
    outcome = repository.ingest(
        result,
        (),
        idempotency_key=key,
        correlation_id=f"correlation_{key}",
    )
    return outcome.candidates[0].candidate_id


def test_explicit_conflict_resolution_is_atomic_and_restart_safe(
    tmp_path: Path,
) -> None:
    path = (tmp_path / "conflict.sqlite3").resolve()
    learning, _ = _registry(path)
    left_id = _ingest_feedback(
        learning,
        _fact_feedback("feedback_left", "locale alpha"),
        key="feedback_left",
    )
    right_id = _ingest_feedback(
        learning,
        _fact_feedback("feedback_right", "locale beta"),
        key="feedback_right",
    )
    conflict = learning.open_conflicts()[0]
    assert conflict.candidate_ids == tuple(sorted((left_id, right_id)))
    request = ConflictResolutionRequest(
        conflict_id=conflict.conflict_id,
        candidate_ids=conflict.candidate_ids,
        candidate_revisions=tuple(
            learning.get_candidate_head(candidate_id).revision
            for candidate_id in conflict.candidate_ids
        ),
        actor_type=ActorType.USER,
        actor_id="actor_conflict_reviewer",
        decision=ConflictResolutionDecision.REJECT_LEFT,
        reason="Explicitly reject the left conflicting fact.",
        reason_code="reject_left_conflict",
        evidence_digests=(digest("conflict evidence"),),
        correlation_id="correlation_conflict_resolution",
        idempotency_key="resolve_conflict_once",
    )
    service = ConflictReviewService(learning)
    outcome = service.resolve(request)
    assert outcome.closed is True
    assert learning.open_conflicts() == ()
    states = tuple(
        learning.get_candidate_head(candidate_id).state
        for candidate_id in conflict.candidate_ids
    )
    assert states == (CandidateState.REJECTED, CandidateState.UNDER_REVIEW)

    restarted_learning, _ = _registry(path)
    assert restarted_learning.open_conflicts() == ()
    replay = ConflictReviewService(restarted_learning).resolve(request)
    assert replay.idempotent is True
    assert replay.candidate_revisions == outcome.candidate_revisions


def test_unresolved_conflict_does_not_close_or_choose_winner(tmp_path: Path) -> None:
    learning, _ = _registry((tmp_path / "conflict.sqlite3").resolve())
    _ingest_feedback(
        learning,
        _fact_feedback("feedback_left", "locale alpha"),
        key="feedback_left",
    )
    _ingest_feedback(
        learning,
        _fact_feedback("feedback_right", "locale beta"),
        key="feedback_right",
    )
    conflict = learning.open_conflicts()[0]
    request = ConflictResolutionRequest(
        conflict_id=conflict.conflict_id,
        candidate_ids=conflict.candidate_ids,
        candidate_revisions=tuple(
            learning.get_candidate_head(candidate_id).revision
            for candidate_id in conflict.candidate_ids
        ),
        actor_type=ActorType.USER,
        actor_id="actor_conflict_reviewer",
        decision=ConflictResolutionDecision.UNRESOLVED,
        reason="Evidence is not yet sufficient.",
        reason_code="conflict_unresolved",
        evidence_digests=(digest("insufficient evidence"),),
        correlation_id="correlation_conflict_unresolved",
        idempotency_key="leave_conflict_open",
    )
    outcome = ConflictReviewService(learning).resolve(request)
    assert outcome.closed is False
    assert len(learning.open_conflicts()) == 1
    assert all(
        learning.get_candidate_head(candidate_id).state is CandidateState.QUARANTINED
        for candidate_id in conflict.candidate_ids
    )
