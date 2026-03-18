"""Backward-compat: verify router is still importable from intelligence.

The canonical tests live in tests/learning/test_router.py. This file
verifies the backward-compat shim in intelligence/router.py works.
"""

from __future__ import annotations

from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import ModelSpec
from openjarvis.intelligence.router import (
    HeuristicRouter,
    build_routing_context,
)
from openjarvis.learning._stubs import RoutingContext


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


class TestShimImports:
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
