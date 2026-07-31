"""Hermetic API tests for Phase-7 learning, routing, feedback, and safety."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.core.config import JarvisConfig  # noqa: E402
from openjarvis.learning.evaluation.models import (  # noqa: E402
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
from openjarvis.learning.runtime import Phase7LearningRuntime  # noqa: E402
from openjarvis.server.app import create_app  # noqa: E402
from openjarvis.tasks.service import TaskService  # noqa: E402
from openjarvis.tasks.store import TaskStore  # noqa: E402
from openjarvis.tasks.types import TaskStatus  # noqa: E402

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _snapshot() -> EvaluationInput:
    evidence_types = (
        EvidenceType.TASK_STATE,
        EvidenceType.TASK_OUTCOME,
        EvidenceType.VERIFICATION_RESULT,
        EvidenceType.POLICY_RESULT,
        EvidenceType.APPROVAL_RESULT,
        EvidenceType.BUDGET_RESULT,
    )
    source_kinds = (
        EvidenceSourceKind.TASK_EVENT,
        EvidenceSourceKind.TASK_RECORD,
        EvidenceSourceKind.VERIFICATION_RECORD,
        EvidenceSourceKind.POLICY_DECISION,
        EvidenceSourceKind.APPROVAL_RECORD,
        EvidenceSourceKind.USAGE_RECORD,
    )
    evidence = tuple(
        EvidenceReference(
            evidence_id=f"evidence-{index}",
            evidence_type=evidence_type,
            source_kind=source_kind,
            source_id=f"source-{index}",
            digest=_digest(f"evidence-{index}"),
            verification_state=EvidenceVerificationState.VERIFIED,
            trusted_boundary=TrustedBoundary.CANONICAL_RUNTIME,
            created_at=NOW,
        )
        for index, (evidence_type, source_kind) in enumerate(
            zip(evidence_types, source_kinds, strict=True)
        )
    )
    return EvaluationInput(
        task_id="task-phase7-api",
        session_id="session-phase7-api",
        correlation_id="correlation-phase7-api",
        trace_id="trace-phase7-api",
        task_type="synthetic.api",
        requested_goal="Verify the synthetic Phase-7 API workflow",
        terminal_task_state=TaskStatus.DONE,
        task_outcome=CanonicalTaskOutcome.COMPLETED,
        verification_state=VerificationState.PASSED,
        approval_state=ApprovalState.NOT_REQUIRED,
        policy_result=PolicyResult.NOT_REQUIRED,
        browser_recovery_state=BrowserRecoveryState.NOT_APPLICABLE,
        evidence_state=EvidenceState.SUFFICIENT,
        budget_state=BudgetState.WITHIN_LIMITS,
        external_effect_state=ExternalEffectState.NONE,
        evidence_references=evidence,
        relevant_event_ids=("event-terminal",),
    )


@pytest.fixture
def api(tmp_path: Path):
    task_store = TaskStore(tmp_path / "tasks.sqlite3")
    task_service = TaskService(task_store)
    task_service.create(
        task_id="task-phase7-api",
        session_id="session-phase7-api",
        correlation_id="task-correlation",
        description="Synthetic API task",
        component="phase7_test",
        cause="synthetic_fixture",
        idempotency_key="task-create",
    )
    runtime = Phase7LearningRuntime.create(tmp_path / "learning.sqlite3")
    app = create_app(
        SimpleNamespace(),
        "synthetic-model",
        config=JarvisConfig(),
        task_store=task_store,
        task_service=task_service,
        phase7_learning_runtime=runtime,
        api_key="phase7-test-key",
    )
    with TestClient(app) as client:
        yield client, task_service, runtime, tmp_path
    task_store.close()


def _headers(key: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer phase7-test-key",
        "X-Correlation-ID": "correlation-phase7-api",
        "Idempotency-Key": key,
    }


def test_required_routes_are_on_the_existing_app(api) -> None:
    client, _tasks, _runtime, _tmp_path = api
    required = {
        ("GET", "/v1/learning/health"),
        ("GET", "/v1/learning/evaluations"),
        ("GET", "/v1/learning/evaluations/{evaluation_id}"),
        ("GET", "/v1/learning/candidates"),
        ("GET", "/v1/learning/candidates/{candidate_id}"),
        ("GET", "/v1/learning/candidates/{candidate_id}/history"),
        ("GET", "/v1/learning/conflicts"),
        ("GET", "/v1/learning/routing/recommendations"),
        ("GET", "/v1/tasks/{task_id}/learning"),
        ("GET", "/v1/skills/{skill_id}"),
        ("GET", "/v1/skills/{skill_id}/versions"),
        ("GET", "/v1/skills/{skill_id}/metrics"),
        ("GET", "/v1/skills/{skill_id}/executions"),
        ("GET", "/v1/tasks/{task_id}/feedback"),
        ("POST", "/v1/learning/evaluate"),
        ("POST", "/v1/learning/candidates/{candidate_id}/review"),
        ("POST", "/v1/learning/candidates/{candidate_id}/reject"),
        ("POST", "/v1/learning/conflicts/{conflict_id}/resolve"),
        ("POST", "/v1/skills/{skill_id}/test"),
        ("POST", "/v1/skills/{skill_id}/request-promotion"),
        ("POST", "/v1/skills/{skill_id}/decide-promotion"),
        ("POST", "/v1/skills/{skill_id}/activate"),
        ("POST", "/v1/skills/{skill_id}/deprecate"),
        ("POST", "/v1/skills/{skill_id}/rollback"),
        ("POST", "/v1/tasks/{task_id}/feedback"),
        ("POST", "/v1/feedback/{feedback_id}/revise"),
        ("POST", "/v1/feedback/{feedback_id}/revoke"),
    }
    inventory = {
        (method, route.path)
        for route in client.app.routes
        for method in getattr(route, "methods", set())
    }
    assert required <= inventory


def test_auth_health_evaluation_and_restart_readback_are_safe(api) -> None:
    client, tasks, runtime, tmp_path = api
    assert client.get("/v1/learning/health").status_code == 401

    health = client.get(
        "/v1/learning/health",
        headers={"Authorization": "Bearer phase7-test-key"},
    )
    assert health.status_code == 200
    payload = health.json()
    assert payload["shadow_routing"]["shadow_mode"] is True
    assert payload["feedback_store"]["approval_authority"] is False
    assert payload["recovery_status"] == "restart_readback_verified"
    assert str(tmp_path) not in health.text

    response = client.post(
        "/v1/learning/evaluate",
        headers=_headers("evaluation-once"),
        json={
            "snapshot": _snapshot().model_dump(mode="json"),
            "project": "synthetic-project",
            "scope": "project",
            "actor": "local-user",
            "expected_revision": 0,
        },
    )
    assert response.status_code == 200, response.text
    evaluation = response.json()["evaluation"]
    assert evaluation["evaluation_class"] == "completed"
    assert response.json()["ingest"]["candidates"]
    listed = client.get(
        "/v1/learning/candidates",
        headers={"Authorization": "Bearer phase7-test-key"},
    )
    assert listed.status_code == 200
    candidate = next(
        item for item in listed.json()["candidates"] if item["state"] == "proposed"
    )

    started_review = client.post(
        f"/v1/learning/candidates/{candidate['candidate_id']}/review",
        headers=_headers("candidate-review-once"),
        json={
            "task_id": "task-phase7-api",
            "session_id": "session-phase7-api",
            "actor": "local-user",
            "expected_revision": candidate["revision"],
            "reason": "Synthetic evidence reviewed through the canonical API.",
            "reason_code": "synthetic_review_started",
            "evidence_reference_ids": candidate["source_evidence_ids"],
        },
    )
    assert started_review.status_code == 200, started_review.text
    before_restart = client.get(
        f"/v1/learning/candidates/{candidate['candidate_id']}/history",
        headers={"Authorization": "Bearer phase7-test-key"},
    )
    assert before_restart.status_code == 200
    assert len(before_restart.json()["revisions"]) == 2
    assert len(before_restart.json()["reviews"]) == 1

    replay = client.post(
        "/v1/learning/evaluate",
        headers=_headers("evaluation-once"),
        json={
            "snapshot": _snapshot().model_dump(mode="json"),
            "project": "synthetic-project",
            "scope": "project",
            "actor": "local-user",
            "expected_revision": 0,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["evaluation"]["evaluation_id"] == evaluation["evaluation_id"]

    restarted = Phase7LearningRuntime.create(runtime.database.path)
    assert restarted.learning.get_evaluation(
        evaluation["evaluation_id"]
    ).evaluation_hash
    restarted_history = restarted.learning.candidate_history(
        candidate["candidate_id"]
    )
    assert [item.model_dump(mode="json") for item in restarted_history] == (
        before_restart.json()["revisions"]
    )
    events = tasks.timeline("task-phase7-api")
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert sum(event.event_type == "evaluation.completed" for event in events) == 1


def test_shadow_route_and_feedback_flow_do_not_change_authority(api) -> None:
    client, tasks, runtime, _tmp_path = api
    routing_evidence = {
        "reference_id": "event-routing",
        "reference_kind": "task_event",
        "digest": _digest("event-routing"),
    }
    route = client.post(
        "/v1/learning/routing/recommend",
        headers=_headers("routing-once"),
        json={
            "actor": "local-user",
            "expected_revision": 0,
            "context": {
                "task_id": "task-phase7-api",
                "session_id": "session-phase7-api",
                "correlation_id": "correlation-phase7-api",
                "task_type": "synthetic.api",
                "productive_route": "python_sdk",
                "productive_risk": 1,
                "route_estimates": {
                    "python_sdk": {"risk": 1, "cost": 0.2, "latency_ms": 100},
                    "read_only_analysis": {
                        "risk": 1,
                        "cost": 0.1,
                        "latency_ms": 50,
                    },
                },
                "evidence_references": [routing_evidence],
                "sample_size": 2,
                "read_only": True,
            },
        },
    )
    assert route.status_code == 200, route.text
    recommendation = route.json()
    assert recommendation["shadow_mode"] is True
    assert recommendation["actual_route"] == "python_sdk"
    assert recommendation["recommended_route"] == "read_only_analysis"

    compared = client.post(
        "/v1/learning/routing/recommendations/"
        f"{recommendation['recommendation_id']}/compare",
        headers=_headers("routing-compare"),
        json={
            "task_id": "task-phase7-api",
            "session_id": "session-phase7-api",
            "actor": "local-user",
            "expected_revision": 0,
            "actual_route": "python_sdk",
            "actual_risk": 1,
            "actual_cost": 0.25,
            "actual_latency": 120,
            "verified_success": True,
            "evidence_references": [routing_evidence],
        },
    )
    assert compared.status_code == 200, compared.text

    feedback = client.post(
        "/v1/tasks/task-phase7-api/feedback",
        headers=_headers("feedback-once"),
        json={
            "session_id": "session-phase7-api",
            "actor": "local-user",
            "answer_id": "answer-phase7",
            "feedback_type": "correction",
            "structured_content": {
                "target_reference": "answer-phase7",
                "corrected_summary": "Use canonical evidence only.",
            },
            "source_digest": _digest("answer-phase7"),
            "expected_revision": 0,
        },
    )
    assert feedback.status_code == 200, feedback.text
    feedback_id = feedback.json()["record"]["feedback_id"]
    assert feedback.json()["candidate_hint"]["review_required"] is True

    revised = client.post(
        f"/v1/feedback/{feedback_id}/revise",
        headers=_headers("feedback-revise"),
        json={
            "task_id": "task-phase7-api",
            "session_id": "session-phase7-api",
            "actor": "local-user",
            "feedback_type": "partially_correct",
            "structured_content": {"summary": "Only partly correct."},
            "expected_revision": 1,
        },
    )
    assert revised.status_code == 200, revised.text
    revoked = client.post(
        f"/v1/feedback/{feedback_id}/revoke",
        headers=_headers("feedback-revoke"),
        json={
            "task_id": "task-phase7-api",
            "session_id": "session-phase7-api",
            "actor": "local-user",
            "expected_revision": 2,
        },
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["record"]["revoked_at"] is not None
    assert [item.revision for item in runtime.feedback.history(feedback_id)] == [
        1,
        2,
        3,
    ]

    with runtime.database.reader() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM skill_promotion_records"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM skill_activation_records"
            ).fetchone()[0]
            == 0
        )
    event_types = {event.event_type for event in tasks.timeline("task-phase7-api")}
    assert {
        "routing.recommended",
        "routing.shadow_compared",
        "feedback.recorded",
        "feedback.revised",
        "feedback.revoked",
    } <= event_types


def test_skill_decisions_require_structured_allow_once_and_runners(api) -> None:
    client, _tasks, _runtime, _tmp_path = api
    base = {
        "task_id": "task-phase7-api",
        "session_id": "session-phase7-api",
        "semantic_version": "1.0.0",
        "actor": "local-user",
        "expected_candidate_revision": 1,
        "expected_state_revision": 1,
        "evidence_reference_ids": ["evidence-review"],
        "scope_key": "project-scope",
        "expected_scope_revision": 0,
        "reason_code": "explicit_review",
    }
    free_yes = client.post(
        "/v1/skills/synthetic-skill/activate",
        headers=_headers("free-yes"),
        json={**base, "decision": "yes"},
    )
    assert free_yes.status_code == 422

    denied = client.post(
        "/v1/skills/synthetic-skill/activate",
        headers=_headers("activation-deny"),
        json={**base, "decision": "deny"},
    )
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"

    allowed = client.post(
        "/v1/skills/synthetic-skill/activate",
        headers=_headers("activation-allow"),
        json={**base, "decision": "allow_once"},
    )
    assert allowed.status_code == 503
    assert "healthcheck runner" in allowed.json()["detail"]
