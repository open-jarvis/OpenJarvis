"""Offline end-to-end smoke for the complete controlled skill lifecycle."""

from __future__ import annotations

import socket
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from openjarvis.learning.lifecycle import ActorType
from openjarvis.learning.skills import (
    ActivationDecision,
    CanonicalSkillExecutor,
    LocalSkillPackageService,
    SkillLifecycleService,
    SkillMetricObservation,
    VerifiedSkillMetricService,
)
from openjarvis.tasks.policy import RiskLevel
from tests.learning.candidates.conftest import make_evaluation

from .test_execution_safety import _ActionServiceDouble, _request
from .test_promotion_lifecycle import (
    _activate,
    _healthcheck,
    _promote,
    _verified_version,
)
from .test_registry import _registry


@pytest.mark.asyncio
async def test_offline_skill_lifecycle_restart_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def network_forbidden(*args, **kwargs):
        raise AssertionError("hermetic skill smoke attempted network access")

    monkeypatch.setattr(socket.socket, "connect", network_forbidden)
    temporary_parent = tmp_path.resolve()
    with TemporaryDirectory(dir=temporary_parent) as raw_root:
        root = Path(raw_root).resolve()
        database_path = (root / "learning.sqlite3").resolve()
        learning, registry = _registry(database_path)
        lifecycle = SkillLifecycleService(registry)

        candidate_one, manifest_one, verified_one = _verified_version(
            learning,
            registry,
            suffix="smoke_v1",
            version="1.0.0",
        )
        requested_one, promoted_one = _promote(
            lifecycle, verified_one, suffix="smoke_v1"
        )
        assert requested_one.skill_head.lifecycle_state.value == "promotion_pending"
        assert promoted_one.skill_head.lifecycle_state.value == "promoted"
        with registry.database.reader() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM skill_scope_heads").fetchone()[
                    0
                ]
                == 0
            )
        active_one = _activate(
            lifecycle,
            promoted_one.skill_head,
            suffix="smoke_v1",
            scope_revision=0,
            previous_version=None,
        )
        assert active_one.skill_head.lifecycle_state.value == "active"

        metric_request = _request(
            task_id="task_smoke_metric_v1",
            session_id="session_smoke_metric_v1",
            correlation_id="correlation_smoke_metric_v1",
            thread_id="thread_smoke_metric_v1",
            turn_id="turn_smoke_metric_v1",
            item_id="item_smoke_metric_v1",
            scope_key="project_fixture",
            idempotency_key="execute_smoke_metric_v1",
        )
        metric_executor = CanonicalSkillExecutor(
            registry, action_service=_ActionServiceDouble()
        )
        metric_pin = metric_executor.pin_active(metric_request)
        metric_execution = await metric_executor.execute_pinned(
            metric_pin.pin_id, metric_request
        )
        evaluation = make_evaluation(
            evaluation_id="evaluation_smoke_v1",
            task_id=metric_request.task_id,
            session_id=metric_request.session_id,
            correlation_id=metric_request.correlation_id,
            trace_id="trace_smoke_v1",
            task_type="synthetic.skill.smoke",
        )
        learning.persist_evaluation(
            evaluation,
            idempotency_key="persist_evaluation_smoke_v1",
            correlation_id=metric_request.correlation_id,
        )
        metrics = VerifiedSkillMetricService(registry).observe(
            SkillMetricObservation(
                observation_id="observation_smoke_v1",
                skill_id=manifest_one.skill_id,
                semantic_version=manifest_one.semantic_version,
                execution_id=metric_execution.execution_id,
                evaluation_id=evaluation.evaluation_id,
                evaluation_hash=evaluation.evaluation_hash,
            ),
            correlation_id=metric_request.correlation_id,
            idempotency_key="observe_metrics_smoke_v1",
        )
        assert metrics.verified_successes == 1

        running_request = _request(
            task_id="task_running_smoke_v1",
            session_id="session_running_smoke_v1",
            correlation_id="correlation_running_smoke_v1",
            thread_id="thread_running_smoke_v1",
            turn_id="turn_running_smoke_v1",
            item_id="item_running_smoke_v1",
            scope_key="project_fixture",
            idempotency_key="execute_running_smoke_v1",
        )
        running_executor = CanonicalSkillExecutor(
            registry, action_service=_ActionServiceDouble()
        )
        running_pin = running_executor.pin_active(running_request)
        assert running_pin.semantic_version == "1.0.0"

        candidate_two, manifest_two, verified_two = _verified_version(
            learning,
            registry,
            suffix="smoke_v2",
            version="2.0.0",
            supersedes_version="1.0.0",
        )
        _, promoted_two = _promote(lifecycle, verified_two, suffix="smoke_v2")
        active_two = _activate(
            lifecycle,
            promoted_two.skill_head,
            suffix="smoke_v2",
            scope_revision=1,
            previous_version="1.0.0",
        )
        assert active_two.skill_head.lifecycle_state.value == "active"
        pinned_completion = await running_executor.execute_pinned(
            running_pin.pin_id, running_request
        )
        assert pinned_completion.semantic_version == "1.0.0"

        new_request = _request(
            task_id="task_new_smoke_v2",
            session_id="session_new_smoke_v2",
            correlation_id="correlation_new_smoke_v2",
            thread_id="thread_new_smoke_v2",
            turn_id="turn_new_smoke_v2",
            item_id="item_new_smoke_v2",
            scope_key="project_fixture",
            idempotency_key="execute_new_smoke_v2",
            task_risk_level=RiskLevel.READ_ONLY,
        )
        new_executor = CanonicalSkillExecutor(
            registry, action_service=_ActionServiceDouble()
        )
        new_pin = new_executor.pin_active(new_request)
        assert new_pin.semantic_version == "2.0.0"
        new_completion = await new_executor.execute_pinned(new_pin.pin_id, new_request)
        assert new_completion.semantic_version == "2.0.0"

        rollback = lifecycle.rollback(
            scope_key="project_fixture",
            expected_scope_revision=2,
            current_skill_id=manifest_two.skill_id,
            current_semantic_version=manifest_two.semantic_version,
            target_skill_id=manifest_one.skill_id,
            target_semantic_version=manifest_one.semantic_version,
            decision=ActivationDecision.ALLOW_ONCE,
            actor_type=ActorType.DETERMINISTIC_TEST,
            actor_id="actor_smoke_lifecycle",
            reason_code="synthetic_smoke_rollback",
            correlation_id="correlation_smoke_rollback",
            evidence_reference_ids=("smoke_rollback_evidence",),
            idempotency_key="rollback_smoke_to_v1",
            healthcheck_runner=_healthcheck,
        )
        assert rollback.target_head.lifecycle_state.value == "active"

        package_path = (root / "skill-package.json").resolve()
        packages = LocalSkillPackageService(registry)
        exported = packages.export_package(
            skill_id=manifest_one.skill_id,
            semantic_version=manifest_one.semantic_version,
            destination=package_path,
            actor_type=ActorType.DETERMINISTIC_TEST,
            actor_id="actor_smoke_package",
            correlation_id="correlation_smoke_export",
            idempotency_key="export_smoke_package",
        )
        imported = packages.import_package(
            source=package_path,
            actor_type=ActorType.DETERMINISTIC_TEST,
            actor_id="actor_smoke_package",
            correlation_id="correlation_smoke_import",
            idempotency_key="import_smoke_package",
        )
        assert imported.quarantined is True
        assert imported.package.package_hash == exported.package.package_hash

        restarted_learning, restarted_registry = _registry(database_path)
        restarted_lifecycle = SkillLifecycleService(restarted_registry)
        assert restarted_lifecycle.active_manifest("project_fixture") == manifest_one
        assert len(restarted_registry.versions(manifest_one.skill_id)) == 2
        assert (
            VerifiedSkillMetricService(restarted_registry)
            .latest(manifest_one.skill_id, manifest_one.semantic_version)
            .verified_successes
            == 1
        )
        assert restarted_learning.get_candidate_head(candidate_one).revision >= 1
        assert restarted_learning.get_candidate_head(candidate_two).revision >= 1
        assert (
            restarted_registry.get_manifest(
                manifest_two.skill_id, manifest_two.semantic_version
            )
            == manifest_two
        )
    assert not root.exists()
