"""Authenticated local API for the final Phase-7 learning and skill surfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.learning.candidates.models import CandidateScope, CandidateState
from openjarvis.learning.evaluation.models import EvaluationInput
from openjarvis.learning.feedback_store import FeedbackType
from openjarvis.learning.lifecycle.conflicts import (
    ConflictResolutionDecision,
    ConflictResolutionRequest,
)
from openjarvis.learning.lifecycle.models import ActorType, TransitionRequest
from openjarvis.learning.phase7_store import (
    Phase7IdempotencyConflict,
    Phase7RecordNotFound,
    Phase7RevisionConflict,
    Phase7StoreError,
    digest,
    utc_now,
)
from openjarvis.learning.routing.shadow import (
    RoutingContext,
    RoutingEvidenceReference,
    RoutingRoute,
)
from openjarvis.learning.skills.promotion import (
    ActivationDecision,
    PromotionDecision,
)
from openjarvis.learning.skills.registry import SkillRegistryError
from openjarvis.learning.store.repository import (
    ExpectedRevisionError,
    IdempotencyConflictError,
    LearningRecordNotFoundError,
    LearningStoreError,
)
from openjarvis.server.task_routes import _mutation_context

router = APIRouter(prefix="/v1", tags=["phase7-learning"])

Identifier = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvaluateRequest(StrictRequest):
    snapshot: EvaluationInput
    project: Identifier
    scope: CandidateScope = CandidateScope.PROJECT
    actor: Identifier
    expected_revision: Literal[0] = 0


class CandidateDecisionRequest(StrictRequest):
    task_id: Identifier
    session_id: Identifier
    actor: Identifier
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=256)
    reason_code: Identifier
    evidence_reference_ids: tuple[Identifier, ...]


class ConflictDecisionRequest(StrictRequest):
    task_id: Identifier
    session_id: Identifier
    actor: Identifier
    candidate_ids: tuple[Identifier, Identifier]
    candidate_revisions: tuple[int, int]
    decision: ConflictResolutionDecision
    reason: str = Field(min_length=1, max_length=256)
    reason_code: Identifier
    evidence_digests: tuple[Digest, ...]


class RoutingRecommendationRequest(StrictRequest):
    context: RoutingContext
    actor: Identifier
    expected_revision: Literal[0] = 0


class RoutingComparisonRequest(StrictRequest):
    task_id: Identifier
    session_id: Identifier
    actor: Identifier
    expected_revision: Literal[0] = 0
    actual_route: RoutingRoute
    actual_risk: int = Field(ge=0, le=4)
    actual_cost: float = Field(ge=0.0)
    actual_latency: int = Field(ge=0)
    verified_success: bool
    evidence_references: tuple[RoutingEvidenceReference, ...]


class FeedbackCreateRequest(StrictRequest):
    session_id: Identifier
    actor: Identifier
    answer_id: Identifier | None = None
    execution_id: Identifier | None = None
    feedback_type: FeedbackType
    structured_content: dict[str, Any]
    source_digest: Digest
    expected_revision: Literal[0] = 0


class FeedbackReviseRequest(StrictRequest):
    task_id: Identifier
    session_id: Identifier
    actor: Identifier
    feedback_type: FeedbackType
    structured_content: dict[str, Any]
    expected_revision: int = Field(ge=1)


class FeedbackRevokeRequest(StrictRequest):
    task_id: Identifier
    session_id: Identifier
    actor: Identifier
    expected_revision: int = Field(ge=1)


class SkillMutationBase(StrictRequest):
    task_id: Identifier
    session_id: Identifier
    semantic_version: str = Field(
        pattern=(
            r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
        ),
        max_length=128,
    )
    actor: Identifier
    expected_candidate_revision: int = Field(ge=1)
    expected_state_revision: int = Field(ge=1)
    evidence_reference_ids: tuple[Identifier, ...]


class SkillTestRequest(SkillMutationBase):
    pass


class PromotionRequest(SkillMutationBase):
    activation_intended: bool = False
    evidence_digests: tuple[Digest, ...]
    reason_code: Identifier


class PromotionDecisionRequest(SkillMutationBase):
    request_promotion_id: Identifier
    decision: Literal["allow_once", "deny"]
    evidence_digests: tuple[Digest, ...]
    reason_code: Identifier


class ActivationRequest(SkillMutationBase):
    scope_key: Identifier
    expected_scope_revision: int = Field(ge=0)
    expected_active_skill_id: Identifier | None = None
    expected_active_semantic_version: str | None = None
    decision: Literal["allow_once", "deny"]
    reason_code: Identifier


class DeprecationRequest(SkillMutationBase):
    scope_key: Identifier | None = None
    expected_scope_revision: int | None = Field(default=None, ge=1)
    reason_code: Identifier


class RollbackRequest(StrictRequest):
    task_id: Identifier
    session_id: Identifier
    actor: Identifier
    scope_key: Identifier
    expected_scope_revision: int = Field(ge=1)
    current_semantic_version: str
    target_semantic_version: str
    decision: Literal["allow_once", "deny"]
    reason_code: Identifier
    evidence_reference_ids: tuple[Identifier, ...]


def _runtime(request: Request):
    runtime = getattr(request.app.state, "phase7_learning_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Phase-7 learning is disabled")
    return runtime


def _task_service(request: Request):
    service = getattr(request.app.state, "task_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail="Canonical task runtime is disabled"
        )
    return service


def _mutation(
    request: Request,
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> tuple[str, str]:
    return _mutation_context(request, correlation_id, idempotency_key)


def _require_task(request: Request, task_id: str, session_id: str):
    service = _task_service(request)
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Canonical task not found")
    if task.session_id != session_id:
        raise HTTPException(status_code=409, detail="Task session binding mismatch")
    return service, task


def _call(operation):  # noqa: ANN001, ANN202
    try:
        return operation()
    except HTTPException:
        raise
    except (Phase7RecordNotFound, LearningRecordNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        Phase7IdempotencyConflict,
        Phase7RevisionConflict,
        IdempotencyConflictError,
        ExpectedRevisionError,
        SkillRegistryError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, Phase7StoreError, LearningStoreError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _append_timeline(
    service,
    *,
    task_id: str,
    source_event_id: str,
    event_type: str,
    cause: str,
    reference_ids: tuple[str, ...],
    hashes: tuple[str, ...] = (),
) -> None:
    event, created = service.store.append_event(
        task_id=task_id,
        source_event_id=source_event_id,
        event_type=event_type,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        cause=cause,
        component="phase7_learning_api",
        payload={
            "reference_ids": sorted(set(reference_ids)),
            "hashes": sorted(set(hashes)),
            "metadata_only": True,
        },
    )
    if created:
        service.project_committed(event)


def _record_denial(
    runtime,
    *,
    operation: str,
    task_id: str,
    session_id: str,
    correlation_id: str,
    idempotency_key: str,
    actor: str,
    reference_ids: tuple[str, ...],
) -> bool:
    request_digest = digest(
        {
            "operation": operation,
            "task_id": task_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "actor": actor,
            "reference_ids": sorted(reference_ids),
            "decision": "deny",
        }
    )
    with runtime.database.transaction() as connection:
        replay = runtime.coordinator.replay(
            connection,
            namespace="skill_api",
            idempotency_key=idempotency_key,
            operation=operation,
            request_digest=request_digest,
        )
        if replay is not None:
            return True
        now = utc_now()
        runtime.coordinator.append_audit(
            connection,
            event_type=f"{operation}.denied",
            task_id=task_id,
            session_id=session_id,
            correlation_id=correlation_id,
            actor=actor,
            reference_ids=reference_ids,
            created_at=now,
        )
        runtime.coordinator.complete(
            connection,
            namespace="skill_api",
            idempotency_key=idempotency_key,
            operation=operation,
            request_digest=request_digest,
            result_references={"denied": True},
            created_at=now,
        )
    return False


def _append_api_audit(
    runtime,
    *,
    operation: str,
    event_type: str,
    task_id: str,
    session_id: str,
    correlation_id: str,
    idempotency_key: str,
    actor: str,
    reference_ids: tuple[str, ...],
) -> None:
    request_digest = digest(
        {
            "operation": operation,
            "event_type": event_type,
            "task_id": task_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "actor": actor,
            "reference_ids": sorted(reference_ids),
        }
    )
    namespace = f"api_audit.{operation}"
    with runtime.database.transaction() as connection:
        replay = runtime.coordinator.replay(
            connection,
            namespace=namespace,
            idempotency_key=idempotency_key,
            operation=operation,
            request_digest=request_digest,
        )
        if replay is not None:
            return
        now = utc_now()
        event_id = runtime.coordinator.append_audit(
            connection,
            event_type=event_type,
            task_id=task_id,
            session_id=session_id,
            correlation_id=correlation_id,
            actor=actor,
            reference_ids=reference_ids,
            created_at=now,
        )
        runtime.coordinator.complete(
            connection,
            namespace=namespace,
            idempotency_key=idempotency_key,
            operation=operation,
            request_digest=request_digest,
            result_references={"event_id": event_id},
            created_at=now,
        )


@router.get("/learning/health")
def learning_health(request: Request) -> dict[str, Any]:
    return _runtime(request).health()


@router.get("/learning/evaluations")
def list_evaluations(
    request: Request,
    task_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    return {"evaluations": _runtime(request).evaluations(task_id=task_id, limit=limit)}


@router.get("/learning/evaluations/{evaluation_id}")
def get_evaluation(evaluation_id: str, request: Request):  # noqa: ANN201
    return _call(lambda: _runtime(request).learning.get_evaluation(evaluation_id))


@router.get("/learning/candidates")
def list_candidates(
    request: Request,
    state: CandidateState | None = None,
) -> dict[str, Any]:
    return {"candidates": _runtime(request).learning.candidates(state=state)}


@router.get("/learning/candidates/{candidate_id}")
def get_candidate(candidate_id: str, request: Request):  # noqa: ANN201
    return _call(lambda: _runtime(request).learning.get_candidate_head(candidate_id))


@router.get("/learning/candidates/{candidate_id}/history")
def candidate_history(candidate_id: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "candidate_id": candidate_id,
        "revisions": _call(lambda: runtime.learning.candidate_history(candidate_id)),
        "reviews": _call(lambda: runtime.learning.transition_history(candidate_id)),
    }


@router.get("/learning/conflicts")
def learning_conflicts(request: Request) -> dict[str, Any]:
    return {"conflicts": _runtime(request).learning.open_conflicts()}


@router.get("/learning/routing/recommendations")
def routing_recommendations(
    request: Request,
    task_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    return {
        "recommendations": _runtime(request).routing.list(task_id=task_id, limit=limit)
    }


@router.get("/tasks/{task_id}/learning")
def task_learning(task_id: str, request: Request) -> dict[str, Any]:
    service = _task_service(request)
    if service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Canonical task not found")
    return _runtime(request).task_learning(task_id)


@router.get("/skills/{skill_id}")
def skill_detail(skill_id: str, request: Request) -> dict[str, Any]:
    return _call(lambda: _runtime(request).skill_detail(skill_id))


@router.get("/skills/{skill_id}/versions")
def skill_versions(skill_id: str, request: Request) -> dict[str, Any]:
    detail = _call(lambda: _runtime(request).skill_detail(skill_id))
    return {"skill_id": skill_id, "versions": detail["versions"]}


@router.get("/skills/{skill_id}/metrics")
def skill_metrics(skill_id: str, request: Request) -> dict[str, Any]:
    detail = _call(lambda: _runtime(request).skill_detail(skill_id))
    return {
        "skill_id": skill_id,
        "metrics": tuple(
            metric for version in detail["versions"] for metric in version["metrics"]
        ),
    }


@router.get("/skills/{skill_id}/executions")
def skill_executions(skill_id: str, request: Request) -> dict[str, Any]:
    detail = _call(lambda: _runtime(request).skill_detail(skill_id))
    return {
        "skill_id": skill_id,
        "executions": tuple(
            execution
            for version in detail["versions"]
            for execution in version["executions"]
        ),
    }


@router.get("/tasks/{task_id}/feedback")
def task_feedback(task_id: str, request: Request) -> dict[str, Any]:
    service = _task_service(request)
    if service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Canonical task not found")
    runtime = _runtime(request)
    feedback = runtime.feedback.list_for_task(task_id)
    return {
        "task_id": task_id,
        "feedback": feedback,
        "history": {
            item.feedback_id: runtime.feedback.history(item.feedback_id)
            for item in feedback
        },
    }


@router.post("/learning/evaluate")
def evaluate(
    body: EvaluateRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(
        request, body.snapshot.task_id, body.snapshot.session_id
    )
    if body.snapshot.correlation_id != correlation_id:
        raise HTTPException(status_code=409, detail="Correlation-ID mismatch")
    evaluation, outcome = _call(
        lambda: _runtime(request).evaluate_and_extract(
            body.snapshot,
            project=body.project,
            scope=body.scope,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    )
    _call(
        lambda: _append_api_audit(
            _runtime(request),
            operation="learning.evaluate",
            event_type="evaluation.completed",
            task_id=evaluation.task_id,
            session_id=evaluation.session_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            actor=body.actor,
            reference_ids=(evaluation.evaluation_id,),
        )
    )
    _append_timeline(
        service,
        task_id=evaluation.task_id,
        source_event_id=f"phase7-evaluation:{idempotency_key}",
        event_type="evaluation.completed",
        cause="deterministic_trace_evaluation",
        reference_ids=(evaluation.evaluation_id,),
        hashes=(evaluation.evaluation_hash,),
    )
    for candidate in outcome.candidates:
        head = _runtime(request).learning.get_candidate_head(candidate.candidate_id)
        _append_timeline(
            service,
            task_id=evaluation.task_id,
            source_event_id=(
                f"phase7-candidate:{idempotency_key}:{candidate.candidate_id}"
            ),
            event_type=(
                "candidate.quarantined"
                if head.state is CandidateState.QUARANTINED
                else "candidate.created"
            ),
            cause="deterministic_candidate_extraction",
            reference_ids=(candidate.candidate_id, evaluation.evaluation_id),
            hashes=(head.content_hash,),
        )
    return {"evaluation": evaluation, "ingest": outcome}


def _candidate_transition(
    candidate_id: str,
    body: CandidateDecisionRequest,
    request: Request,
    mutation: tuple[str, str],
    target: CandidateState,
):  # noqa: ANN202
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    candidate = _call(
        lambda: _runtime(request).learning.get_candidate_head(candidate_id)
    )
    if candidate.source_task_ids and body.task_id not in candidate.source_task_ids:
        raise HTTPException(status_code=409, detail="Candidate task binding mismatch")
    outcome = _call(
        lambda: _runtime(request).learning.transition(
            TransitionRequest(
                candidate_id=candidate_id,
                expected_revision=body.expected_revision,
                target_state=target,
                actor_type=ActorType.USER,
                actor_id=body.actor,
                reason=body.reason,
                reason_code=body.reason_code,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                evidence_reference_ids=body.evidence_reference_ids,
            )
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-candidate-review:{idempotency_key}",
        event_type="candidate.revised",
        cause=body.reason_code,
        reference_ids=(candidate_id, outcome.transition.transition_id),
        hashes=(outcome.content_hash,),
    )
    return outcome


@router.post("/learning/candidates/{candidate_id}/review")
def review_candidate(
    candidate_id: str,
    body: CandidateDecisionRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    return _candidate_transition(
        candidate_id, body, request, mutation, CandidateState.UNDER_REVIEW
    )


@router.post("/learning/candidates/{candidate_id}/reject")
def reject_candidate(
    candidate_id: str,
    body: CandidateDecisionRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    return _candidate_transition(
        candidate_id, body, request, mutation, CandidateState.REJECTED
    )


@router.post("/learning/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: str,
    body: ConflictDecisionRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    outcome = _call(
        lambda: _runtime(request).conflicts.resolve(
            ConflictResolutionRequest(
                conflict_id=conflict_id,
                candidate_ids=body.candidate_ids,
                candidate_revisions=body.candidate_revisions,
                actor_type=ActorType.USER,
                actor_id=body.actor,
                decision=body.decision,
                reason=body.reason,
                reason_code=body.reason_code,
                evidence_digests=body.evidence_digests,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-conflict:{idempotency_key}",
        event_type="conflict.resolved",
        cause=body.reason_code,
        reference_ids=(conflict_id, outcome.record.resolution_id),
        hashes=(outcome.record.resolution_hash,),
    )
    return outcome


@router.post("/learning/routing/recommend")
def recommend_route(
    body: RoutingRecommendationRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    context = body.context
    service, _task = _require_task(request, context.task_id, context.session_id)
    if context.correlation_id != correlation_id:
        raise HTTPException(status_code=409, detail="Correlation-ID mismatch")
    record = _call(
        lambda: _runtime(request).routing.recommend(
            context,
            idempotency_key=idempotency_key,
            expected_revision=body.expected_revision,
            actor=body.actor,
        )
    )
    _append_timeline(
        service,
        task_id=context.task_id,
        source_event_id=f"phase7-routing:{idempotency_key}",
        event_type="routing.recommended",
        cause="shadow_routing_only",
        reference_ids=(record.recommendation_id,),
        hashes=(record.recommendation_hash,),
    )
    return record


@router.post("/learning/routing/recommendations/{recommendation_id}/compare")
def compare_route(
    recommendation_id: str,
    body: RoutingComparisonRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    _correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    existing = _call(lambda: _runtime(request).routing.get(recommendation_id))
    if (
        existing.recommendation.task_id != body.task_id
        or existing.recommendation.session_id != body.session_id
    ):
        raise HTTPException(status_code=409, detail="Routing task binding mismatch")
    comparison = _call(
        lambda: _runtime(request).routing.compare(
            recommendation_id,
            actual_route=body.actual_route,
            actual_risk=body.actual_risk,
            actual_cost=body.actual_cost,
            actual_latency=body.actual_latency,
            verified_success=body.verified_success,
            evidence_references=body.evidence_references,
            idempotency_key=idempotency_key,
            expected_revision=body.expected_revision,
            actor=body.actor,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-routing-compare:{idempotency_key}",
        event_type="routing.shadow_compared",
        cause="shadow_route_comparison",
        reference_ids=(recommendation_id, comparison.comparison_id),
        hashes=(comparison.comparison_hash,),
    )
    return comparison


@router.post("/tasks/{task_id}/feedback")
def record_feedback(
    task_id: str,
    body: FeedbackCreateRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, task_id, body.session_id)
    outcome = _call(
        lambda: _runtime(request).feedback.record(
            task_id=task_id,
            session_id=body.session_id,
            correlation_id=correlation_id,
            answer_id=body.answer_id,
            execution_id=body.execution_id,
            actor=body.actor,
            feedback_type=body.feedback_type,
            structured_content=body.structured_content,
            source_digest=body.source_digest,
            idempotency_key=idempotency_key,
            expected_revision=body.expected_revision,
        )
    )
    _append_timeline(
        service,
        task_id=task_id,
        source_event_id=f"phase7-feedback:{idempotency_key}",
        event_type="feedback.recorded",
        cause="explicit_user_feedback",
        reference_ids=(outcome.record.feedback_id,),
        hashes=(outcome.record.feedback_hash,),
    )
    return outcome


@router.post("/feedback/{feedback_id}/revise")
def revise_feedback(
    feedback_id: str,
    body: FeedbackReviseRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    existing = _call(lambda: _runtime(request).feedback.get(feedback_id))
    if existing.task_id != body.task_id or existing.session_id != body.session_id:
        raise HTTPException(status_code=409, detail="Feedback task binding mismatch")
    outcome = _call(
        lambda: _runtime(request).feedback.revise(
            feedback_id,
            expected_revision=body.expected_revision,
            actor=body.actor,
            feedback_type=body.feedback_type,
            structured_content=body.structured_content,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-feedback-revise:{idempotency_key}",
        event_type="feedback.revised",
        cause="explicit_user_feedback_revision",
        reference_ids=(feedback_id,),
        hashes=(outcome.record.feedback_hash,),
    )
    return outcome


@router.post("/feedback/{feedback_id}/revoke")
def revoke_feedback(
    feedback_id: str,
    body: FeedbackRevokeRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    existing = _call(lambda: _runtime(request).feedback.get(feedback_id))
    if existing.task_id != body.task_id or existing.session_id != body.session_id:
        raise HTTPException(status_code=409, detail="Feedback task binding mismatch")
    outcome = _call(
        lambda: _runtime(request).feedback.revoke(
            feedback_id,
            expected_revision=body.expected_revision,
            actor=body.actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-feedback-revoke:{idempotency_key}",
        event_type="feedback.revoked",
        cause="explicit_user_feedback_revocation",
        reference_ids=(feedback_id,),
        hashes=(outcome.record.feedback_hash,),
    )
    return outcome


@router.post("/skills/{skill_id}/test")
def test_skill(
    skill_id: str,
    body: SkillTestRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    runtime = _runtime(request)
    runner = getattr(request.app.state, "phase7_skill_test_runner", None)
    if runner is None:
        raise HTTPException(
            status_code=503,
            detail="Deterministic skill test runner is not configured",
        )
    head = _call(
        lambda: runtime.verification.start_testing(
            skill_id=skill_id,
            semantic_version=body.semantic_version,
            expected_candidate_revision=body.expected_candidate_revision,
            expected_state_revision=body.expected_state_revision,
            actor_type=ActorType.USER,
            actor_id=body.actor,
            correlation_id=correlation_id,
            idempotency_key=f"{idempotency_key}.start",
            evidence_reference_ids=body.evidence_reference_ids,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-skill-test-start:{idempotency_key}",
        event_type="skill.test_started",
        cause="explicit_hermetic_skill_test",
        reference_ids=(skill_id, body.semantic_version),
    )
    manifest = runtime.registry.get_manifest(skill_id, body.semantic_version)
    verification_record = _call(lambda: runner(manifest, head))
    outcome = _call(
        lambda: runtime.verification.verify(
            verification_record,
            expected_state_revision=head.state_revision,
            actor_type=ActorType.DETERMINISTIC_TEST,
            actor_id="phase7-api-test-runner",
            correlation_id=correlation_id,
            idempotency_key=f"{idempotency_key}.verify",
        )
    )
    event_type = (
        "skill.verified"
        if outcome.record.status.value == "passed"
        else "skill.execution_failed"
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-skill-test-result:{idempotency_key}",
        event_type=event_type,
        cause="deterministic_skill_verification",
        reference_ids=(skill_id, outcome.record.verification_id),
        hashes=(outcome.record.verification_hash,),
    )
    return outcome


@router.post("/skills/{skill_id}/request-promotion")
def request_promotion(
    skill_id: str,
    body: PromotionRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    outcome = _call(
        lambda: _runtime(request).lifecycle.request_promotion(
            skill_id=skill_id,
            semantic_version=body.semantic_version,
            expected_candidate_revision=body.expected_candidate_revision,
            expected_state_revision=body.expected_state_revision,
            activation_intended=body.activation_intended,
            actor_type=ActorType.USER,
            actor_id=body.actor,
            reason_code=body.reason_code,
            correlation_id=correlation_id,
            evidence_reference_ids=body.evidence_reference_ids,
            evidence_digests=body.evidence_digests,
            idempotency_key=idempotency_key,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-promotion-request:{idempotency_key}",
        event_type="skill.promotion_requested",
        cause=body.reason_code,
        reference_ids=(skill_id, outcome.record.promotion_id),
        hashes=(outcome.record.record_hash,),
    )
    return outcome


@router.post("/skills/{skill_id}/decide-promotion")
def decide_promotion(
    skill_id: str,
    body: PromotionDecisionRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    outcome = _call(
        lambda: _runtime(request).lifecycle.decide_promotion(
            request_promotion_id=body.request_promotion_id,
            decision=PromotionDecision(body.decision),
            expected_candidate_revision=body.expected_candidate_revision,
            expected_state_revision=body.expected_state_revision,
            actor_type=ActorType.USER,
            actor_id=body.actor,
            reason_code=body.reason_code,
            correlation_id=correlation_id,
            evidence_reference_ids=body.evidence_reference_ids,
            evidence_digests=body.evidence_digests,
            idempotency_key=idempotency_key,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-promotion-decision:{idempotency_key}",
        event_type=(
            "skill.promoted"
            if body.decision == "allow_once"
            else "skill.promotion_denied"
        ),
        cause=body.reason_code,
        reference_ids=(skill_id, outcome.record.promotion_id),
        hashes=(outcome.record.record_hash,),
    )
    return outcome


@router.post("/skills/{skill_id}/activate")
def activate_skill(
    skill_id: str,
    body: ActivationRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    runtime = _runtime(request)
    if body.decision == "deny":
        replay = _record_denial(
            runtime,
            operation="skill.activation",
            task_id=body.task_id,
            session_id=body.session_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            actor=body.actor,
            reference_ids=(skill_id, body.semantic_version),
        )
        return {"status": "denied", "idempotent": replay}
    runner = getattr(request.app.state, "phase7_healthcheck_runner", None)
    if runner is None:
        raise HTTPException(
            status_code=503,
            detail="Deterministic skill healthcheck runner is not configured",
        )
    outcome = _call(
        lambda: runtime.lifecycle.activate(
            skill_id=skill_id,
            semantic_version=body.semantic_version,
            expected_candidate_revision=body.expected_candidate_revision,
            expected_state_revision=body.expected_state_revision,
            scope_key=body.scope_key,
            expected_scope_revision=body.expected_scope_revision,
            expected_active_skill_id=body.expected_active_skill_id,
            expected_active_semantic_version=body.expected_active_semantic_version,
            decision=ActivationDecision.ALLOW_ONCE,
            actor_type=ActorType.USER,
            actor_id=body.actor,
            reason_code=body.reason_code,
            correlation_id=correlation_id,
            evidence_reference_ids=body.evidence_reference_ids,
            idempotency_key=idempotency_key,
            healthcheck_runner=runner,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-activation:{idempotency_key}",
        event_type="skill.activated",
        cause=body.reason_code,
        reference_ids=(skill_id, outcome.record.activation_id),
        hashes=(outcome.record.record_hash,),
    )
    return outcome


@router.post("/skills/{skill_id}/deprecate")
def deprecate_skill(
    skill_id: str,
    body: DeprecationRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    record = _call(
        lambda: _runtime(request).lifecycle.deprecate(
            skill_id=skill_id,
            semantic_version=body.semantic_version,
            expected_candidate_revision=body.expected_candidate_revision,
            expected_state_revision=body.expected_state_revision,
            scope_key=body.scope_key,
            expected_scope_revision=body.expected_scope_revision,
            actor_type=ActorType.USER,
            actor_id=body.actor,
            reason_code=body.reason_code,
            correlation_id=correlation_id,
            evidence_reference_ids=body.evidence_reference_ids,
            idempotency_key=idempotency_key,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-deprecation:{idempotency_key}",
        event_type="skill.deprecated",
        cause=body.reason_code,
        reference_ids=(skill_id, record.deprecation_id),
        hashes=(record.record_hash,),
    )
    return record


@router.post("/skills/{skill_id}/rollback")
def rollback_skill(
    skill_id: str,
    body: RollbackRequest,
    request: Request,
    mutation: tuple[str, str] = Depends(_mutation),
):  # noqa: ANN201
    correlation_id, idempotency_key = mutation
    service, _task = _require_task(request, body.task_id, body.session_id)
    runtime = _runtime(request)
    if body.decision == "deny":
        replay = _record_denial(
            runtime,
            operation="skill.rollback",
            task_id=body.task_id,
            session_id=body.session_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            actor=body.actor,
            reference_ids=(
                skill_id,
                body.current_semantic_version,
                body.target_semantic_version,
            ),
        )
        return {"status": "denied", "idempotent": replay}
    runner = getattr(request.app.state, "phase7_healthcheck_runner", None)
    if runner is None:
        raise HTTPException(
            status_code=503,
            detail="Deterministic skill healthcheck runner is not configured",
        )
    outcome = _call(
        lambda: runtime.lifecycle.rollback(
            scope_key=body.scope_key,
            expected_scope_revision=body.expected_scope_revision,
            current_skill_id=skill_id,
            current_semantic_version=body.current_semantic_version,
            target_skill_id=skill_id,
            target_semantic_version=body.target_semantic_version,
            decision=ActivationDecision.ALLOW_ONCE,
            actor_type=ActorType.USER,
            actor_id=body.actor,
            reason_code=body.reason_code,
            correlation_id=correlation_id,
            evidence_reference_ids=body.evidence_reference_ids,
            idempotency_key=idempotency_key,
            healthcheck_runner=runner,
        )
    )
    _append_timeline(
        service,
        task_id=body.task_id,
        source_event_id=f"phase7-rollback:{idempotency_key}",
        event_type="skill.rolled_back",
        cause=body.reason_code,
        reference_ids=(skill_id, outcome.record.rollback_id),
        hashes=(outcome.record.record_hash,),
    )
    return outcome


__all__ = ["router"]
