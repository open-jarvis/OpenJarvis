"""Hermetic promotion, activation, deprecation and rollback tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openjarvis.learning.lifecycle import ActorType
from openjarvis.learning.skills import (
    REQUIRED_VERIFICATION_TYPES,
    ActivationDecision,
    FixtureClass,
    PromotionDecision,
    SkillHealthcheckResult,
    SkillLifecycleService,
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
from tests.learning.candidates.conftest import NOW, digest

from .test_manifest_legacy import valid_draft
from .test_registry import _register, _registry, _seed_reviewed_skill


def _verification(
    *, candidate_id: str, manifest: SkillManifest, suffix: str, revision: int
) -> SkillVerificationRecord:
    test_types = list(sorted(REQUIRED_VERIFICATION_TYPES, key=lambda item: item.value))
    test_types.extend((SkillTestType.POSITIVE, SkillTestType.POSITIVE))
    cases = []
    results = []
    for index, test_type in enumerate(test_types):
        holdout = index == len(test_types) - 1
        fixture_id = f"fixture_{suffix}_{'holdout' if holdout else 'development'}"
        test_id = f"test_{suffix}_{test_type.value}_{index}"
        evidence = digest(f"evidence_{test_id}")
        cases.append(
            SkillTestCase.create(
                {
                    "test_id": test_id,
                    "test_version": 1,
                    "test_type": test_type,
                    "fixture_id": fixture_id,
                    "fixture_class": (
                        FixtureClass.HOLDOUT if holdout else FixtureClass.DEVELOPMENT
                    ),
                    "input_digest": digest(f"input_{test_id}"),
                    "expected_evidence_digests": (evidence,),
                    "expected_outcome": "completed",
                    "created_at": NOW,
                }
            )
        )
        results.append(
            SkillTestResult.create(
                {
                    "result_id": f"result_{suffix}_{test_type.value}_{index}",
                    "test_id": test_id,
                    "test_version": 1,
                    "test_type": test_type,
                    "fixture_id": fixture_id,
                    "passed": True,
                    "effect_known": True,
                    "canonical_outcome": "completed",
                    "evidence_digests": (evidence,),
                    "duration_seconds": 0.01,
                    "created_at": NOW,
                }
            )
        )
    run = SkillTestRun.create(
        {
            "run_id": f"verification_run_{suffix}",
            "skill_id": manifest.skill_id,
            "semantic_version": manifest.semantic_version,
            "candidate_id": candidate_id,
            "candidate_revision": revision,
            "manifest_hash": manifest.content_hash,
            "hermetic": True,
            "test_cases": tuple(cases),
            "test_results": tuple(results),
            "created_at": NOW,
            "completed_at": NOW,
        }
    )
    evidence_digests = tuple(
        sorted({item for result in results for item in result.evidence_digests})
    )
    return SkillVerificationRecord.create(
        {
            "verification_id": f"verification_{suffix}",
            "run": run,
            "status": VerificationStatus.PASSED,
            "required_test_types": tuple(REQUIRED_VERIFICATION_TYPES),
            "fixture_ids": tuple(sorted({case.fixture_id for case in cases})),
            "holdout_fixture_ids": tuple(
                sorted(
                    case.fixture_id
                    for case in cases
                    if case.fixture_class is FixtureClass.HOLDOUT
                )
            ),
            "activation_ready": True,
            "evidence_digests": evidence_digests,
            "created_at": NOW,
        }
    )


def _verified_version(learning, registry, *, suffix: str, version: str):
    candidate_id = _seed_reviewed_skill(learning, suffix=suffix)
    updates = {
        "origin_candidate_id": candidate_id,
        "origin_candidate_revision": 2,
        "semantic_version": version,
        "description": f"Read bounded synthetic fixture version {version}.",
    }
    if version != "1.0.0":
        updates["supersedes_version"] = "1.0.0"
    manifest = SkillManifest.create(valid_draft(**updates))
    _register(registry, manifest, key=f"register_{suffix}")
    verifier = SkillVerificationService(registry)
    testing = verifier.start_testing(
        skill_id=manifest.skill_id,
        semantic_version=version,
        expected_candidate_revision=2,
        expected_state_revision=1,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_lifecycle_fixture",
        correlation_id=f"correlation_testing_{suffix}",
        idempotency_key=f"testing_{suffix}",
        evidence_reference_ids=(f"review_{suffix}",),
    )
    record = _verification(
        candidate_id=candidate_id,
        manifest=manifest,
        suffix=suffix,
        revision=testing.candidate_revision,
    )
    verified = verifier.verify(
        record,
        expected_state_revision=testing.state_revision,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_lifecycle_fixture",
        correlation_id=f"correlation_verification_{suffix}",
        idempotency_key=f"verify_{suffix}",
    )
    return candidate_id, manifest, verified.skill_head


def _promote(service: SkillLifecycleService, head, *, suffix: str):
    requested = service.request_promotion(
        skill_id=head.skill_id,
        semantic_version=head.semantic_version,
        expected_candidate_revision=head.candidate_revision,
        expected_state_revision=head.state_revision,
        activation_intended=True,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_lifecycle_fixture",
        reason_code="synthetic_promotion_review",
        correlation_id=f"correlation_promotion_request_{suffix}",
        evidence_reference_ids=(f"promotion_evidence_{suffix}",),
        evidence_digests=(digest(f"promotion_evidence_{suffix}"),),
        idempotency_key=f"promotion_request_{suffix}",
    )
    promoted = service.decide_promotion(
        request_promotion_id=requested.record.promotion_id,
        decision=PromotionDecision.ALLOW_ONCE,
        expected_candidate_revision=requested.candidate_revision,
        expected_state_revision=requested.skill_head.state_revision,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_lifecycle_fixture",
        reason_code="synthetic_promotion_allowed_once",
        correlation_id=f"correlation_promotion_decision_{suffix}",
        evidence_reference_ids=(f"promotion_decision_{suffix}",),
        evidence_digests=(digest(f"promotion_decision_{suffix}"),),
        idempotency_key=f"promotion_decide_{suffix}",
    )
    return requested, promoted


def _healthcheck(manifest: SkillManifest) -> SkillHealthcheckResult:
    suffix = manifest.semantic_version.replace(".", "_")
    return SkillHealthcheckResult.create(
        {
            "healthcheck_id": f"healthcheck_{suffix}",
            "skill_id": manifest.skill_id,
            "semantic_version": manifest.semantic_version,
            "manifest_hash": manifest.content_hash,
            "passed": True,
            "evidence_reference_ids": (f"healthcheck_evidence_{suffix}",),
            "evidence_digests": (digest(f"healthcheck_evidence_{suffix}"),),
            "created_at": NOW,
        }
    )


def _activate(
    service: SkillLifecycleService,
    head,
    *,
    suffix: str,
    scope_revision: int,
    previous_version: str | None,
):
    return service.activate(
        skill_id=head.skill_id,
        semantic_version=head.semantic_version,
        expected_candidate_revision=head.candidate_revision,
        expected_state_revision=head.state_revision,
        scope_key="project_fixture",
        expected_scope_revision=scope_revision,
        expected_active_skill_id=head.skill_id if previous_version else None,
        expected_active_semantic_version=previous_version,
        decision=ActivationDecision.ALLOW_ONCE,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_lifecycle_fixture",
        reason_code="synthetic_activation_allowed_once",
        correlation_id=f"correlation_activation_{suffix}",
        evidence_reference_ids=(f"activation_evidence_{suffix}",),
        idempotency_key=f"activate_{suffix}",
        healthcheck_runner=_healthcheck,
    )


def test_promotion_is_explicit_and_does_not_activate(tmp_path: Path) -> None:
    learning, registry = _registry((tmp_path / "promotion.sqlite3").resolve())
    _, manifest, verified = _verified_version(
        learning, registry, suffix="v1", version="1.0.0"
    )
    service = SkillLifecycleService(registry)

    requested = service.request_promotion(
        skill_id=manifest.skill_id,
        semantic_version=manifest.semantic_version,
        expected_candidate_revision=verified.candidate_revision,
        expected_state_revision=verified.state_revision,
        activation_intended=True,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_lifecycle_fixture",
        reason_code="synthetic_promotion_review",
        correlation_id="correlation_promotion_request",
        evidence_reference_ids=("promotion_evidence",),
        evidence_digests=(digest("promotion_evidence"),),
        idempotency_key="promotion_request",
    )

    assert requested.skill_head.lifecycle_state.value == "promotion_pending"
    with pytest.raises(SkillRegistryError, match="promoted"):
        service.activate(
            skill_id=manifest.skill_id,
            semantic_version=manifest.semantic_version,
            expected_candidate_revision=requested.candidate_revision,
            expected_state_revision=requested.skill_head.state_revision,
            scope_key="project_fixture",
            expected_scope_revision=0,
            expected_active_skill_id=None,
            expected_active_semantic_version=None,
            decision=ActivationDecision.ALLOW_ONCE,
            actor_type=ActorType.DETERMINISTIC_TEST,
            actor_id="actor_lifecycle_fixture",
            reason_code="premature_activation",
            correlation_id="correlation_premature_activation",
            evidence_reference_ids=("premature_activation",),
            idempotency_key="premature_activation",
            healthcheck_runner=_healthcheck,
        )
    with pytest.raises(ValueError):
        PromotionDecision("yes")
    with pytest.raises(ValidationError):
        SkillHealthcheckResult.model_validate(
            {**_healthcheck(manifest).model_dump(), "passed": "spoken yes"}
        )
    with registry.database.reader() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM skill_scope_heads").fetchone()[0]
            == 0
        )


def test_promotion_deny_is_terminal_and_never_activates(tmp_path: Path) -> None:
    learning, registry = _registry((tmp_path / "deny.sqlite3").resolve())
    _, _, verified = _verified_version(
        learning, registry, suffix="deny", version="1.0.0"
    )
    service = SkillLifecycleService(registry)
    requested = service.request_promotion(
        skill_id=verified.skill_id,
        semantic_version=verified.semantic_version,
        expected_candidate_revision=verified.candidate_revision,
        expected_state_revision=verified.state_revision,
        activation_intended=False,
        actor_type=ActorType.USER,
        actor_id="actor_local_user",
        reason_code="promotion_review_requested",
        correlation_id="correlation_deny_request",
        evidence_reference_ids=("deny_request_evidence",),
        evidence_digests=(digest("deny_request_evidence"),),
        idempotency_key="deny_promotion_request",
    )
    denied = service.decide_promotion(
        request_promotion_id=requested.record.promotion_id,
        decision=PromotionDecision.DENY,
        expected_candidate_revision=requested.candidate_revision,
        expected_state_revision=requested.skill_head.state_revision,
        actor_type=ActorType.USER,
        actor_id="actor_local_user",
        reason_code="promotion_denied",
        correlation_id="correlation_deny_decision",
        evidence_reference_ids=("deny_decision_evidence",),
        evidence_digests=(digest("deny_decision_evidence"),),
        idempotency_key="deny_promotion_decision",
    )
    assert denied.skill_head.lifecycle_state.value == "rejected"


def test_activation_is_cas_idempotent_and_restart_safe(tmp_path: Path) -> None:
    path = (tmp_path / "activation.sqlite3").resolve()
    learning, registry = _registry(path)
    _, manifest, verified = _verified_version(
        learning, registry, suffix="v1", version="1.0.0"
    )
    service = SkillLifecycleService(registry)
    _, promoted = _promote(service, verified, suffix="v1")
    activated = _activate(
        service,
        promoted.skill_head,
        suffix="v1",
        scope_revision=0,
        previous_version=None,
    )
    replay = _activate(
        service,
        promoted.skill_head,
        suffix="v1",
        scope_revision=0,
        previous_version=None,
    )
    assert activated.skill_head.lifecycle_state.value == "active"
    assert replay.idempotent is True
    assert service.active_manifest("project_fixture") == manifest

    _, restarted_registry = _registry(path)
    restarted = SkillLifecycleService(restarted_registry)
    assert restarted.active_manifest("project_fixture") == manifest
    assert restarted.get_activation(activated.record.activation_id) == activated.record

    with pytest.raises(SkillRegistryError, match="promoted"):
        restarted.activate(
            skill_id=manifest.skill_id,
            semantic_version=manifest.semantic_version,
            expected_candidate_revision=activated.skill_head.candidate_revision,
            expected_state_revision=activated.skill_head.state_revision,
            scope_key="project_fixture",
            expected_scope_revision=0,
            expected_active_skill_id=None,
            expected_active_semantic_version=None,
            decision=ActivationDecision.ALLOW_ONCE,
            actor_type=ActorType.DETERMINISTIC_TEST,
            actor_id="actor_lifecycle_fixture",
            reason_code="competing_activation",
            correlation_id="correlation_competing_activation",
            evidence_reference_ids=("competing_activation",),
            idempotency_key="competing_activation",
            healthcheck_runner=_healthcheck,
        )


def test_version_switch_deprecates_previous_and_rollback_restores_it(
    tmp_path: Path,
) -> None:
    path = (tmp_path / "rollback.sqlite3").resolve()
    learning, registry = _registry(path)
    service = SkillLifecycleService(registry)
    _, manifest_one, verified_one = _verified_version(
        learning, registry, suffix="v1", version="1.0.0"
    )
    _, promoted_one = _promote(service, verified_one, suffix="v1")
    active_one = _activate(
        service,
        promoted_one.skill_head,
        suffix="v1",
        scope_revision=0,
        previous_version=None,
    )

    _, manifest_two, verified_two = _verified_version(
        learning, registry, suffix="v2", version="2.0.0"
    )
    _, promoted_two = _promote(service, verified_two, suffix="v2")
    active_two = _activate(
        service,
        promoted_two.skill_head,
        suffix="v2",
        scope_revision=1,
        previous_version="1.0.0",
    )
    assert active_two.scope_revision == 2
    assert service.active_manifest("project_fixture") == manifest_two
    assert (
        registry.get_head(manifest_one.skill_id, "1.0.0").lifecycle_state.value
        == "deprecated"
    )

    rolled_back = service.rollback(
        scope_key="project_fixture",
        expected_scope_revision=2,
        current_skill_id=manifest_two.skill_id,
        current_semantic_version="2.0.0",
        target_skill_id=manifest_one.skill_id,
        target_semantic_version="1.0.0",
        decision=ActivationDecision.ALLOW_ONCE,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_lifecycle_fixture",
        reason_code="synthetic_regression_rollback",
        correlation_id="correlation_rollback",
        evidence_reference_ids=("rollback_evidence",),
        idempotency_key="rollback_to_v1",
        healthcheck_runner=_healthcheck,
    )
    assert rolled_back.current_head.lifecycle_state.value == "rolled_back"
    assert rolled_back.target_head.lifecycle_state.value == "active"
    assert service.active_manifest("project_fixture") == manifest_one
    assert registry.get_manifest(manifest_two.skill_id, "2.0.0") == manifest_two
    assert registry.get_manifest(manifest_one.skill_id, "1.0.0") == manifest_one
    assert len(registry.versions(manifest_one.skill_id)) == 2
    assert active_one.record != active_two.record

    _, restarted_registry = _registry(path)
    assert (
        SkillLifecycleService(restarted_registry).active_manifest("project_fixture")
        == manifest_one
    )


def test_open_conflict_and_failed_healthcheck_block_mutations(
    tmp_path: Path, monkeypatch
) -> None:
    learning, registry = _registry((tmp_path / "blocked.sqlite3").resolve())
    _, manifest, verified = _verified_version(
        learning, registry, suffix="blocked", version="1.0.0"
    )
    service = SkillLifecycleService(registry)
    monkeypatch.setattr(registry.learning, "_has_open_conflict", lambda *_: True)
    with pytest.raises(SkillRegistryError, match="open conflict"):
        service.request_promotion(
            skill_id=manifest.skill_id,
            semantic_version=manifest.semantic_version,
            expected_candidate_revision=verified.candidate_revision,
            expected_state_revision=verified.state_revision,
            activation_intended=True,
            actor_type=ActorType.USER,
            actor_id="actor_local_user",
            reason_code="blocked_promotion",
            correlation_id="correlation_blocked_promotion",
            evidence_reference_ids=("blocked_evidence",),
            evidence_digests=(digest("blocked_evidence"),),
            idempotency_key="blocked_promotion",
        )
