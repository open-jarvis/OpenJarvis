"""Deterministic routing recommendations that can never change production routes."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.phase7_store import (
    Phase7IntegrityError,
    Phase7RecordNotFound,
    Phase7StoreCoordinator,
    digest,
    iso,
    utc_now,
    validate_identifier,
)
from openjarvis.learning.skills.manifest import SkillLifecycleStatus
from openjarvis.learning.skills.registry import SkillRegistry
from openjarvis.learning.store.sqlite import SQLiteLearningDatabase

Identifier = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RoutingRoute(str, Enum):
    PYTHON_SDK = "python_sdk"
    APP_SERVER = "app_server"
    READ_ONLY_ANALYSIS = "read_only_analysis"
    TOOL_TASK = "tool_task"
    MEMORY_FIRST = "memory_first"
    BROWSER_REQUIRED = "browser_required"
    DESKTOP_REQUIRED = "desktop_required"
    VERIFIED_SKILL = "verified_skill"
    HUMAN_CLARIFICATION = "human_clarification"
    REJECT = "reject"


class RoutingComparisonResult(str, Enum):
    MATCHED = "matched"
    ACTUAL_ROUTE_DIFFERED = "actual_route_differed"
    ACTUAL_FAILED = "actual_failed"
    INCONCLUSIVE = "inconclusive"


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RoutingEvidenceReference(StrictFrozenModel):
    reference_id: Identifier
    reference_kind: Identifier
    digest: Digest


class RouteEstimate(StrictFrozenModel):
    risk: int = Field(ge=0, le=4)
    cost: float = Field(ge=0.0, le=1_000_000.0)
    latency_ms: int = Field(ge=0, le=86_400_000)


class RoutingContext(StrictFrozenModel):
    task_id: Identifier
    session_id: Identifier
    correlation_id: Identifier
    task_type: Identifier
    productive_route: RoutingRoute
    productive_risk: int = Field(ge=0, le=4)
    route_estimates: dict[RoutingRoute, RouteEstimate]
    evidence_references: tuple[RoutingEvidenceReference, ...]
    sample_size: int = Field(ge=0)
    requires_browser: bool = False
    requires_desktop: bool = False
    requires_memory: bool = False
    requires_tools: bool = False
    read_only: bool = False
    unsafe: bool = False
    needs_clarification: bool = False
    skill_id: Identifier | None = None
    semantic_version: str | None = Field(
        default=None,
        pattern=(
            r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
        ),
        max_length=128,
    )

    @field_validator("evidence_references")
    @classmethod
    def _evidence_required(
        cls, values: tuple[RoutingEvidenceReference, ...]
    ) -> tuple[RoutingEvidenceReference, ...]:
        by_id = {item.reference_id: item for item in values}
        if len(by_id) != len(values):
            raise ValueError("routing evidence references must be unique")
        if not by_id:
            raise ValueError("routing recommendation requires evidence")
        return tuple(by_id[key] for key in sorted(by_id))

    @model_validator(mode="after")
    def _contract(self) -> Self:
        if (self.skill_id is None) != (self.semantic_version is None):
            raise ValueError("skill_id and semantic_version must appear together")
        if self.productive_route not in self.route_estimates:
            raise ValueError("productive route requires an estimate")
        if self.route_estimates[self.productive_route].risk < self.productive_risk:
            raise ValueError("productive route estimate may not lower current risk")
        return self


class _RoutingRecommendationPayload(StrictFrozenModel):
    recommendation_id: Identifier
    task_id: Identifier
    session_id: Identifier
    correlation_id: Identifier
    task_type: Identifier
    recommended_route: RoutingRoute
    alternative_routes: tuple[RoutingRoute, ...]
    evidence_references: tuple[RoutingEvidenceReference, ...]
    skill_id: Identifier | None = None
    semantic_version: str | None = None
    expected_risk: int = Field(ge=0, le=4)
    expected_cost: float = Field(ge=0.0)
    expected_latency: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_basis: tuple[Identifier, ...]
    known_limitations: tuple[str, ...]
    sample_size: int = Field(ge=0)
    small_sample: bool
    shadow_mode: Literal[True] = True
    actual_route: RoutingRoute
    comparison_result: Literal["pending"] = "pending"
    created_at: datetime

    @field_validator("alternative_routes")
    @classmethod
    def _alternatives(
        cls, values: tuple[RoutingRoute, ...]
    ) -> tuple[RoutingRoute, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @field_validator("confidence_basis")
    @classmethod
    def _confidence_basis(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("confidence_basis must not be empty")
        return values

    @field_validator("known_limitations")
    @classmethod
    def _limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            sorted({" ".join(value.strip().split()) for value in values})
        )
        if not normalized or any(not value or len(value) > 256 for value in normalized):
            raise ValueError("known_limitations must contain bounded text")
        return normalized

    @model_validator(mode="after")
    def _contract(self) -> Self:
        if (self.skill_id is None) != (self.semantic_version is None):
            raise ValueError("skill identity must be complete")
        if self.recommended_route is RoutingRoute.VERIFIED_SKILL and not self.skill_id:
            raise ValueError("verified_skill recommendation requires a pinned skill")
        if self.recommended_route is not RoutingRoute.VERIFIED_SKILL and self.skill_id:
            raise ValueError("only verified_skill recommendations include a skill")
        if self.recommended_route in self.alternative_routes:
            raise ValueError("recommended route cannot also be an alternative")
        if self.small_sample is not (self.sample_size < 5):
            raise ValueError("small_sample must reflect sample_size")
        return self


class RoutingRecommendation(_RoutingRecommendationPayload):
    recommendation_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, object]) -> "RoutingRecommendation":
        payload = _RoutingRecommendationPayload.model_validate(values)
        serialized = payload.model_dump(mode="json")
        return cls.model_validate(
            {**serialized, "recommendation_hash": digest(serialized)}
        )

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"recommendation_hash"})
        if digest(payload) != self.recommendation_hash:
            raise ValueError("recommendation_hash mismatch")
        return self


class RoutingComparison(StrictFrozenModel):
    comparison_id: Identifier
    recommendation_id: Identifier
    actual_route: RoutingRoute
    actual_risk: int = Field(ge=0, le=4)
    actual_cost: float = Field(ge=0.0)
    actual_latency: int = Field(ge=0)
    verified_success: bool
    comparison_result: RoutingComparisonResult
    evidence_references: tuple[RoutingEvidenceReference, ...]
    created_at: datetime
    comparison_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, object]) -> "RoutingComparison":
        draft = cls.model_construct(**dict(values), comparison_hash="0" * 64)
        payload = draft.model_dump(mode="json", exclude={"comparison_hash"})
        return cls.model_validate({**payload, "comparison_hash": digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"comparison_hash"})
        if digest(payload) != self.comparison_hash:
            raise ValueError("comparison_hash mismatch")
        return self


class RoutingRecommendationView(StrictFrozenModel):
    recommendation: RoutingRecommendation
    comparison: RoutingComparison | None = None


class ShadowRoutingService:
    """Persist recommendations and comparisons without touching route selection."""

    def __init__(
        self,
        database: SQLiteLearningDatabase,
        *,
        registry: SkillRegistry | None = None,
    ) -> None:
        self.database = database
        self.coordinator = Phase7StoreCoordinator(database)
        self.registry = registry

    def recommend(
        self,
        context: RoutingContext,
        *,
        idempotency_key: str,
        expected_revision: int = 0,
        actor: str | None = None,
    ) -> RoutingRecommendation:
        if expected_revision != 0:
            raise ValueError("new recommendations require expected_revision=0")
        validate_identifier(idempotency_key, "idempotency_key")
        if actor is not None:
            validate_identifier(actor, "actor")
        selected, skill_id, version, basis, limitations = self._select(context)
        estimate = context.route_estimates.get(selected)
        if estimate is None:
            raise ValueError(f"missing route estimate for {selected.value}")
        if estimate.risk < context.productive_risk:
            raise ValueError("routing recommendation may never lower risk")
        alternatives = tuple(
            route
            for route in sorted(context.route_estimates, key=lambda item: item.value)
            if route is not selected
            and context.route_estimates[route].risk >= context.productive_risk
        )
        request_digest = digest(
            {
                "context": context.model_dump(mode="json"),
                "selected": selected.value,
                "skill_id": skill_id,
                "semantic_version": version,
                "actor": actor,
            }
        )
        with self.database.transaction() as connection:
            replay = self.coordinator.replay(
                connection,
                namespace="routing",
                idempotency_key=idempotency_key,
                operation="routing.recommend",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._recommendation(connection, replay["recommendation_id"])
            now = utc_now()
            confidence = min(0.98, 0.45 + min(context.sample_size, 20) * 0.025)
            recommendation = RoutingRecommendation.create(
                {
                    "recommendation_id": f"routing_{uuid.uuid4().hex}",
                    "task_id": context.task_id,
                    "session_id": context.session_id,
                    "correlation_id": context.correlation_id,
                    "task_type": context.task_type,
                    "recommended_route": selected,
                    "alternative_routes": alternatives,
                    "evidence_references": context.evidence_references,
                    "skill_id": skill_id,
                    "semantic_version": version,
                    "expected_risk": estimate.risk,
                    "expected_cost": estimate.cost,
                    "expected_latency": estimate.latency_ms,
                    "confidence": confidence,
                    "confidence_basis": basis,
                    "known_limitations": limitations,
                    "sample_size": context.sample_size,
                    "small_sample": context.sample_size < 5,
                    "shadow_mode": True,
                    "actual_route": context.productive_route,
                    "comparison_result": "pending",
                    "created_at": now,
                }
            )
            connection.execute(
                """
                INSERT INTO routing_recommendations(
                    recommendation_id, task_id, session_id, correlation_id,
                    task_type, recommended_route, skill_id, semantic_version,
                    expected_risk, confidence, sample_size,
                    recommendation_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recommendation.recommendation_id,
                    recommendation.task_id,
                    recommendation.session_id,
                    recommendation.correlation_id,
                    recommendation.task_type,
                    recommendation.recommended_route.value,
                    recommendation.skill_id,
                    recommendation.semantic_version,
                    recommendation.expected_risk,
                    recommendation.confidence,
                    recommendation.sample_size,
                    recommendation.recommendation_hash,
                    recommendation.model_dump_json(),
                    iso(recommendation.created_at),
                ),
            )
            self.coordinator.append_audit(
                connection,
                event_type="routing.recommended",
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                actor=actor,
                reference_ids=(recommendation.recommendation_id,),
                created_at=now,
            )
            self.coordinator.complete(
                connection,
                namespace="routing",
                idempotency_key=idempotency_key,
                operation="routing.recommend",
                request_digest=request_digest,
                result_references={
                    "recommendation_id": recommendation.recommendation_id
                },
                created_at=now,
            )
            return recommendation

    def compare(
        self,
        recommendation_id: str,
        *,
        actual_route: RoutingRoute,
        actual_risk: int,
        actual_cost: float,
        actual_latency: int,
        verified_success: bool,
        evidence_references: tuple[RoutingEvidenceReference, ...],
        idempotency_key: str,
        expected_revision: int = 0,
        actor: str | None = None,
    ) -> RoutingComparison:
        if expected_revision != 0:
            raise ValueError("first comparison requires expected_revision=0")
        if not 0 <= actual_risk <= 4:
            raise ValueError("actual_risk must be between 0 and 4")
        if actual_cost < 0 or actual_latency < 0:
            raise ValueError("actual cost and latency must be non-negative")
        if not evidence_references:
            raise ValueError("routing comparison requires verified evidence")
        if actor is not None:
            validate_identifier(actor, "actor")
        request_digest = digest(
            {
                "recommendation_id": recommendation_id,
                "actual_route": actual_route.value,
                "actual_risk": actual_risk,
                "actual_cost": actual_cost,
                "actual_latency": actual_latency,
                "verified_success": verified_success,
                "actor": actor,
                "evidence_references": [
                    item.model_dump(mode="json") for item in evidence_references
                ],
            }
        )
        with self.database.transaction() as connection:
            replay = self.coordinator.replay(
                connection,
                namespace="routing",
                idempotency_key=idempotency_key,
                operation="routing.compare",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._comparison(connection, replay["comparison_id"])
            recommendation = self._recommendation(connection, recommendation_id)
            if actual_risk < recommendation.expected_risk:
                raise ValueError("comparison may not claim a lower risk level")
            result = (
                RoutingComparisonResult.ACTUAL_FAILED
                if not verified_success
                else RoutingComparisonResult.MATCHED
                if actual_route is recommendation.recommended_route
                else RoutingComparisonResult.ACTUAL_ROUTE_DIFFERED
            )
            now = utc_now()
            comparison = RoutingComparison.create(
                {
                    "comparison_id": f"routing_comparison_{uuid.uuid4().hex}",
                    "recommendation_id": recommendation_id,
                    "actual_route": actual_route,
                    "actual_risk": actual_risk,
                    "actual_cost": actual_cost,
                    "actual_latency": actual_latency,
                    "verified_success": verified_success,
                    "comparison_result": result,
                    "evidence_references": evidence_references,
                    "created_at": now,
                }
            )
            connection.execute(
                """
                INSERT INTO routing_comparisons(
                    comparison_id, recommendation_id, actual_route,
                    comparison_result, comparison_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    comparison.comparison_id,
                    recommendation_id,
                    actual_route.value,
                    comparison.comparison_result.value,
                    comparison.comparison_hash,
                    comparison.model_dump_json(),
                    iso(now),
                ),
            )
            self.coordinator.append_audit(
                connection,
                event_type="routing.shadow_compared",
                task_id=recommendation.task_id,
                session_id=recommendation.session_id,
                correlation_id=recommendation.correlation_id,
                actor=actor,
                reference_ids=(recommendation_id, comparison.comparison_id),
                created_at=now,
            )
            self.coordinator.complete(
                connection,
                namespace="routing",
                idempotency_key=idempotency_key,
                operation="routing.compare",
                request_digest=request_digest,
                result_references={"comparison_id": comparison.comparison_id},
                created_at=now,
            )
            return comparison

    def get(self, recommendation_id: str) -> RoutingRecommendationView:
        with self.database.reader() as connection:
            recommendation = self._recommendation(connection, recommendation_id)
            row = connection.execute(
                """
                SELECT comparison_id FROM routing_comparisons
                WHERE recommendation_id = ?
                """,
                (recommendation_id,),
            ).fetchone()
            comparison = (
                self._comparison(connection, row["comparison_id"])
                if row is not None
                else None
            )
            return RoutingRecommendationView(
                recommendation=recommendation,
                comparison=comparison,
            )

    def list(
        self, *, task_id: str | None = None, limit: int = 200
    ) -> tuple[RoutingRecommendationView, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.database.reader() as connection:
            if task_id is None:
                rows = connection.execute(
                    """
                    SELECT recommendation_id FROM routing_recommendations
                    ORDER BY created_at DESC, recommendation_id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                validate_identifier(task_id, "task_id")
                rows = connection.execute(
                    """
                    SELECT recommendation_id FROM routing_recommendations
                    WHERE task_id = ?
                    ORDER BY created_at DESC, recommendation_id DESC LIMIT ?
                    """,
                    (task_id, limit),
                ).fetchall()
            recommendation_ids = tuple(row["recommendation_id"] for row in rows)
        return tuple(
            self.get(recommendation_id) for recommendation_id in recommendation_ids
        )

    def _select(
        self, context: RoutingContext
    ) -> tuple[RoutingRoute, str | None, str | None, tuple[str, ...], tuple[str, ...]]:
        basis = ["deterministic_task_metadata", "productive_route_unchanged"]
        limitations = [
            "Shadow recommendation only; no model, agent, or route is switched."
        ]
        if context.sample_size < 5:
            basis.append("small_sample")
            limitations.append("Small sample; confidence is deliberately capped.")
        skill_id = None
        version = None
        if context.unsafe:
            route = RoutingRoute.REJECT
            basis.append("unsafe_request")
        elif context.needs_clarification:
            route = RoutingRoute.HUMAN_CLARIFICATION
            basis.append("missing_required_context")
        elif context.skill_id and context.semantic_version:
            self._validate_skill(context.skill_id, context.semantic_version)
            route = RoutingRoute.VERIFIED_SKILL
            skill_id = context.skill_id
            version = context.semantic_version
            basis.append("active_promoted_verified_skill")
        elif context.requires_desktop:
            route = RoutingRoute.DESKTOP_REQUIRED
            basis.append("desktop_capability_required")
        elif context.requires_browser:
            route = RoutingRoute.BROWSER_REQUIRED
            basis.append("browser_capability_required")
        elif context.requires_memory:
            route = RoutingRoute.MEMORY_FIRST
            basis.append("memory_evidence_required")
        elif context.requires_tools:
            route = RoutingRoute.TOOL_TASK
            basis.append("tool_capability_required")
        elif context.read_only:
            route = RoutingRoute.READ_ONLY_ANALYSIS
            basis.append("read_only_task")
        else:
            route = context.productive_route
            basis.append("no_safer_deterministic_alternative")
        return route, skill_id, version, tuple(basis), tuple(limitations)

    def _validate_skill(self, skill_id: str, semantic_version: str) -> None:
        if self.registry is None:
            raise ValueError("verified skill routing requires the canonical registry")
        head = self.registry.get_head(skill_id, semantic_version)
        if head.lifecycle_state is not SkillLifecycleStatus.ACTIVE:
            raise ValueError("only an active promoted skill version may be recommended")
        manifest = self.registry.get_manifest(skill_id, semantic_version)
        if manifest.deprecated_at is not None:
            raise ValueError("deprecated skill versions cannot be recommended")
        with self.database.reader() as connection:
            candidate = connection.execute(
                "SELECT state FROM candidate_heads WHERE candidate_id = ?",
                (head.candidate_id,),
            ).fetchone()
            conflict = connection.execute(
                """
                SELECT 1 FROM candidate_conflict_links
                WHERE is_open = 1 AND (candidate_a_id = ? OR candidate_b_id = ?)
                """,
                (head.candidate_id, head.candidate_id),
            ).fetchone()
        if candidate is None or candidate["state"] != "active" or conflict is not None:
            raise ValueError("conflict or quarantine excludes skill recommendation")

    @staticmethod
    def _recommendation(
        connection: sqlite3.Connection, recommendation_id: str
    ) -> RoutingRecommendation:
        row = connection.execute(
            """
            SELECT payload_json, recommendation_hash
            FROM routing_recommendations WHERE recommendation_id = ?
            """,
            (recommendation_id,),
        ).fetchone()
        if row is None:
            raise Phase7RecordNotFound("routing recommendation not found")
        try:
            record = RoutingRecommendation.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise Phase7IntegrityError("routing recommendation decode failed") from exc
        if record.recommendation_hash != row["recommendation_hash"]:
            raise Phase7IntegrityError("routing recommendation index mismatch")
        return record

    @staticmethod
    def _comparison(
        connection: sqlite3.Connection, comparison_id: str
    ) -> RoutingComparison:
        row = connection.execute(
            """
            SELECT payload_json, comparison_hash
            FROM routing_comparisons WHERE comparison_id = ?
            """,
            (comparison_id,),
        ).fetchone()
        if row is None:
            raise Phase7RecordNotFound("routing comparison not found")
        try:
            record = RoutingComparison.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise Phase7IntegrityError("routing comparison decode failed") from exc
        if record.comparison_hash != row["comparison_hash"]:
            raise Phase7IntegrityError("routing comparison index mismatch")
        return record


__all__ = [
    "RouteEstimate",
    "RoutingComparison",
    "RoutingComparisonResult",
    "RoutingContext",
    "RoutingEvidenceReference",
    "RoutingRecommendation",
    "RoutingRecommendationView",
    "RoutingRoute",
    "ShadowRoutingService",
]
