"""Persistent registry, migration-2 and restart integrity tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.learning.candidates import (
    CandidateExtractor,
    CandidateState,
    CandidateType,
    ProposedDestination,
    RollbackExpectation,
    SchemaProposal,
    SkillCandidateContent,
    StructuredCandidateRequest,
)
from openjarvis.learning.candidates import (
    DeclarativeSkillStep as CandidateStep,
)
from openjarvis.learning.lifecycle import ActorType, TransitionRequest
from openjarvis.learning.lifecycle.service import CandidateLifecycleService
from openjarvis.learning.skills import (
    RegistryDisposition,
    SkillManifest,
    SkillRegistry,
    SkillVersionConflictError,
)
from openjarvis.learning.store import (
    IdempotencyConflictError,
    LearningIntegrityError,
    LearningRepository,
    SQLiteLearningDatabase,
)
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tools.manifest import ToolManifestCatalog
from tests.learning.candidates.conftest import NOW, envelope, make_evaluation

from .test_manifest_legacy import _ReadTool, valid_draft

V2_TABLES = {
    "skill_manifests",
    "skill_versions",
    "skill_candidate_links",
    "skill_verification_runs",
    "skill_test_results",
    "skill_promotion_records",
    "skill_activation_records",
    "skill_deprecation_records",
    "skill_rollback_records",
    "skill_execution_records",
    "skill_metric_snapshots",
}


def _seed_reviewed_skill(repository: LearningRepository, *, suffix: str = "a") -> str:
    evaluation = make_evaluation(
        evaluation_id=f"evaluation_skill_{suffix}",
        task_id=f"task_skill_{suffix}",
        session_id=f"session_skill_{suffix}",
        trace_id=f"trace_skill_{suffix}",
        task_type=f"synthetic.skill.{suffix}",
    )
    content = SkillCandidateContent(
        proposed_name=f"synthetic_skill_{suffix}",
        purpose="Read and verify one synthetic fixture.",
        input_schema_proposal=SchemaProposal(),
        output_schema_proposal=SchemaProposal(),
        preconditions=("Synthetic fixture exists.",),
        postconditions=("Verified digest is recorded.",),
        allowed_tool_ids=("file.read",),
        maximum_risk_level=RiskLevel.READ_ONLY,
        proposed_steps=(
            CandidateStep(
                step_id="read_fixture",
                tool_id="file.read",
                purpose="Read bounded fixture metadata.",
            ),
        ),
        negative_cases=("Fixture is absent.",),
        rollback_expectation=RollbackExpectation.NO_EFFECT,
    )
    request = StructuredCandidateRequest(
        request_id=f"request_skill_{suffix}",
        candidate_type=CandidateType.SKILL,
        title="Synthetic skill candidate",
        content=content,
        scope="project",
        project="project_a",
        source_evaluation_ids=(evaluation.evaluation_id,),
        proposed_tests=("Synthetic positive and negative fixtures.",),
        proposed_verification=("Deterministic postcondition check.",),
        proposed_destination=ProposedDestination.SKILL_REGISTRY,
    )
    result = CandidateExtractor().extract(
        (envelope(evaluation),), requests=(request,), created_at=NOW
    )
    extracted = next(
        candidate
        for candidate in result.candidates
        if candidate.candidate_type is CandidateType.SKILL
    )
    outcome = repository.ingest(
        result,
        (evaluation,),
        idempotency_key=f"ingest_skill_{suffix}",
        correlation_id=f"correlation_ingest_{suffix}",
    )
    candidate_id = next(
        item.candidate_id
        for item in outcome.candidates
        if item.extraction_candidate_id == extracted.candidate_id
    )
    CandidateLifecycleService(repository).transition(
        TransitionRequest(
            candidate_id=candidate_id,
            expected_revision=1,
            target_state=CandidateState.UNDER_REVIEW,
            actor_type=ActorType.DETERMINISTIC_TEST,
            actor_id="actor_registry_fixture",
            reason="Synthetic review started.",
            reason_code="review_started",
            correlation_id=f"correlation_review_{suffix}",
            idempotency_key=f"review_skill_{suffix}",
        )
    )
    return candidate_id


def _registry(path: Path) -> tuple[LearningRepository, SkillRegistry]:
    database = SQLiteLearningDatabase(path)
    learning = LearningRepository(database)
    learning.initialize()
    registry = SkillRegistry(
        database,
        learning=learning,
        tool_catalog=ToolManifestCatalog.from_tools([_ReadTool()]),
    )
    return learning, registry


def _register(registry: SkillRegistry, manifest: SkillManifest, *, key: str):
    return registry.register_manifest(
        manifest,
        actor_type=ActorType.DETERMINISTIC_TEST,
        actor_id="actor_registry_fixture",
        reason_code="synthetic_registration",
        correlation_id="correlation_registry",
        idempotency_key=key,
    )


def test_migration_two_registry_schema_survives_later_migrations(
    tmp_path: Path,
) -> None:
    database = SQLiteLearningDatabase((tmp_path / "registry.sqlite3").resolve())
    assert database.initialize() == (1, 2, 3)
    assert database.initialize() == ()
    with database.reader() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        versions = connection.execute(
            "SELECT version FROM learning_schema_migrations ORDER BY version"
        ).fetchall()
    assert V2_TABLES <= tables
    assert [row["version"] for row in versions] == [1, 2, 3]


def test_manifest_registration_round_trip_and_events(tmp_path: Path) -> None:
    learning, registry = _registry((tmp_path / "registry.sqlite3").resolve())
    candidate_id = _seed_reviewed_skill(learning)
    manifest = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
        )
    )

    outcome = _register(registry, manifest, key="register_manifest_once")

    assert outcome.disposition is RegistryDisposition.CREATED
    assert registry.get_manifest(manifest.skill_id, "1.0.0") == manifest
    assert registry.get_version(manifest.skill_id, "1.0.0").registry_revision == 1
    assert registry.get_head(manifest.skill_id, "1.0.0").state_revision == 1
    assert [event.event_type.value for event in registry.events_after()] == [
        "skill.manifest_created",
        "skill.version_registered",
    ]


def test_registration_idempotency_survives_restart(tmp_path: Path) -> None:
    path = (tmp_path / "registry.sqlite3").resolve()
    learning, registry = _registry(path)
    candidate_id = _seed_reviewed_skill(learning)
    manifest = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
        )
    )
    first = _register(registry, manifest, key="register_restart")

    restarted_learning, restarted = _registry(path)
    assert restarted_learning.get_candidate_head(candidate_id).revision == 2
    replay = _register(restarted, manifest, key="register_restart")

    assert first.version == replay.version
    assert replay.disposition is RegistryDisposition.REPLAYED
    assert len(restarted.events_after()) == 2


def test_idempotency_key_with_other_semantics_is_rejected(tmp_path: Path) -> None:
    learning, registry = _registry((tmp_path / "registry.sqlite3").resolve())
    candidate_id = _seed_reviewed_skill(learning)
    first = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
        )
    )
    _register(registry, first, key="register_semantics")
    changed = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
            description="Read a different bounded synthetic fixture.",
        )
    )
    with pytest.raises(IdempotencyConflictError):
        _register(registry, changed, key="register_semantics")


def test_versions_are_append_only_and_historical(tmp_path: Path) -> None:
    learning, registry = _registry((tmp_path / "registry.sqlite3").resolve())
    candidate_id = _seed_reviewed_skill(learning)
    version_one = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
        )
    )
    version_two = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
            semantic_version="1.1.0",
            supersedes_version="1.0.0",
            description="Read two bounded synthetic fixture formats.",
        )
    )
    _register(registry, version_one, key="register_v1")
    _register(registry, version_two, key="register_v2")

    history = registry.versions(version_one.skill_id)
    assert [record.semantic_version for record in history] == ["1.0.0", "1.1.0"]
    assert registry.get_manifest(version_one.skill_id, "1.0.0") == version_one
    assert registry.get_manifest(version_one.skill_id, "1.1.0") == version_two


def test_same_semantic_version_with_other_content_is_rejected(tmp_path: Path) -> None:
    learning, registry = _registry((tmp_path / "registry.sqlite3").resolve())
    candidate_id = _seed_reviewed_skill(learning)
    first = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
        )
    )
    changed = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
            description="Different content under the same semantic version.",
        )
    )
    _register(registry, first, key="register_original")
    with pytest.raises(SkillVersionConflictError, match="different content"):
        _register(registry, changed, key="register_changed")


def test_stale_candidate_revision_is_rejected(tmp_path: Path) -> None:
    learning, registry = _registry((tmp_path / "registry.sqlite3").resolve())
    candidate_id = _seed_reviewed_skill(learning)
    stale = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=1,
        )
    )
    with pytest.raises(SkillVersionConflictError, match="stale"):
        _register(registry, stale, key="register_stale")


def test_tampered_manifest_and_event_are_detected(tmp_path: Path) -> None:
    learning, registry = _registry((tmp_path / "registry.sqlite3").resolve())
    candidate_id = _seed_reviewed_skill(learning)
    manifest = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
        )
    )
    _register(registry, manifest, key="register_tamper")
    with registry.database.transaction() as connection:
        connection.execute(
            "UPDATE skill_manifests SET payload_json = '{}' WHERE content_hash = ?",
            (manifest.content_hash,),
        )
    with pytest.raises(LearningIntegrityError, match="manifest integrity"):
        registry.get_manifest(manifest.skill_id, manifest.semantic_version)

    with registry.database.transaction() as connection:
        connection.execute(
            "UPDATE skill_manifests SET payload_json = ? WHERE content_hash = ?",
            (manifest.model_dump_json(), manifest.content_hash),
        )
        connection.execute(
            "UPDATE skill_audit_events SET payload_json = '{}' WHERE sequence = 1"
        )
    with pytest.raises(LearningIntegrityError, match="event integrity"):
        registry.events_after()
