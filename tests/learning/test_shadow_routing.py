"""Hermetic tests for append-only Phase-7 shadow routing."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from openjarvis.learning.phase7_store import Phase7IdempotencyConflict
from openjarvis.learning.routing.shadow import (
    RouteEstimate,
    RoutingContext,
    RoutingEvidenceReference,
    RoutingRoute,
    ShadowRoutingService,
)
from openjarvis.learning.store.sqlite import SQLiteLearningDatabase


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def database(tmp_path: Path) -> SQLiteLearningDatabase:
    value = SQLiteLearningDatabase((tmp_path / "learning.sqlite3").resolve())
    assert value.initialize() == (1, 2, 3)
    return value


def _context(**changes: object) -> RoutingContext:
    values: dict[str, object] = {
        "task_id": "task-shadow",
        "session_id": "session-shadow",
        "correlation_id": "correlation-shadow",
        "task_type": "analysis",
        "productive_route": RoutingRoute.PYTHON_SDK,
        "productive_risk": 1,
        "route_estimates": {
            RoutingRoute.PYTHON_SDK: RouteEstimate(risk=1, cost=0.2, latency_ms=100),
            RoutingRoute.READ_ONLY_ANALYSIS: RouteEstimate(
                risk=1, cost=0.1, latency_ms=50
            ),
        },
        "evidence_references": (
            RoutingEvidenceReference(
                reference_id="event-1",
                reference_kind="task_event",
                digest=_digest("event-1"),
            ),
        ),
        "sample_size": 2,
        "read_only": True,
    }
    values.update(changes)
    return RoutingContext.model_validate(values)


def test_recommendation_is_shadow_only_append_only_and_restart_safe(
    database: SQLiteLearningDatabase,
) -> None:
    service = ShadowRoutingService(database)
    recommendation = service.recommend(
        _context(), idempotency_key="route-once", expected_revision=0
    )

    assert recommendation.shadow_mode is True
    assert recommendation.recommended_route is RoutingRoute.READ_ONLY_ANALYSIS
    assert recommendation.actual_route is RoutingRoute.PYTHON_SDK
    assert recommendation.comparison_result == "pending"
    assert recommendation.small_sample is True
    assert "small_sample" in recommendation.confidence_basis

    replay = service.recommend(
        _context(), idempotency_key="route-once", expected_revision=0
    )
    assert replay == recommendation

    comparison = service.compare(
        recommendation.recommendation_id,
        actual_route=RoutingRoute.PYTHON_SDK,
        actual_risk=1,
        actual_cost=0.25,
        actual_latency=120,
        verified_success=True,
        evidence_references=_context().evidence_references,
        idempotency_key="compare-once",
    )
    assert comparison.actual_route is RoutingRoute.PYTHON_SDK
    assert comparison.comparison_result.value == "actual_route_differed"

    restarted = ShadowRoutingService(database)
    view = restarted.get(recommendation.recommendation_id)
    assert view.recommendation == recommendation
    assert view.comparison == comparison
    assert restarted.list(task_id="task-shadow") == (view,)


def test_recommendation_never_lowers_risk(
    database: SQLiteLearningDatabase,
) -> None:
    context = _context(
        productive_risk=2,
        route_estimates={
            RoutingRoute.PYTHON_SDK: RouteEstimate(risk=2, cost=0.2, latency_ms=100),
            RoutingRoute.READ_ONLY_ANALYSIS: RouteEstimate(
                risk=1, cost=0.1, latency_ms=50
            ),
        },
    )
    with pytest.raises(ValueError, match="never lower risk"):
        ShadowRoutingService(database).recommend(
            context, idempotency_key="risk-lowering"
        )


def test_skill_route_requires_canonical_active_registry(
    database: SQLiteLearningDatabase,
) -> None:
    context = _context(
        skill_id="verified-skill",
        semantic_version="1.0.0",
        route_estimates={
            **_context().route_estimates,
            RoutingRoute.VERIFIED_SKILL: RouteEstimate(
                risk=2, cost=0.05, latency_ms=20
            ),
        },
    )
    with pytest.raises(ValueError, match="canonical registry"):
        ShadowRoutingService(database).recommend(
            context, idempotency_key="skill-without-registry"
        )


def test_idempotency_conflict_and_hash_tampering_are_visible(
    database: SQLiteLearningDatabase,
) -> None:
    service = ShadowRoutingService(database)
    recommendation = service.recommend(_context(), idempotency_key="route-conflict")
    with pytest.raises(Phase7IdempotencyConflict):
        service.recommend(_context(sample_size=9), idempotency_key="route-conflict")

    connection = sqlite3.connect(database.path)
    connection.execute(
        """
        UPDATE routing_recommendations SET recommendation_hash = ?
        WHERE recommendation_id = ?
        """,
        ("0" * 64, recommendation.recommendation_id),
    )
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="index mismatch"):
        service.get(recommendation.recommendation_id)
