"""Tests for the intelligence router via canonical learning.routing.router imports."""

from __future__ import annotations

from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import ModelSpec
from openjarvis.learning._stubs import RoutingContext
from openjarvis.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)


def _register_models() -> None:
    ModelRegistry.register_value(
        "small",
        ModelSpec(
            model_id="small",
            name="Small",
            parameter_count_b=3.0,
            context_length=4096,
        ),
    )
    ModelRegistry.register_value(
        "large",
        ModelSpec(
            model_id="large",
            name="Large",
            parameter_count_b=70.0,
            context_length=131072,
        ),
    )


class TestRouter:
    def test_build_routing_context(self) -> None:
        ctx = build_routing_context("def hello():\n    pass")
        assert ctx.has_code is True

    def test_heuristic_router(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "large"],
        )
        ctx = RoutingContext(query="Hi", query_length=2)
        assert router.select_model(ctx) == "small"
