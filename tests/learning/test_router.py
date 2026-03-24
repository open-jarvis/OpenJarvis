"""Tests for the heuristic model router (canonical location)."""

from __future__ import annotations

from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import ModelSpec
from openjarvis.learning._stubs import RoutingContext
from openjarvis.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)


def _register_models() -> None:
    """Register a small set of models for testing."""
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
    ModelRegistry.register_value(
        "coder",
        ModelSpec(
            model_id="coder",
            name="DeepSeek Coder",
            parameter_count_b=16.0,
            context_length=131072,
        ),
    )


class TestBuildRoutingContext:
    def test_code_detection(self) -> None:
        ctx = build_routing_context("def hello():\n    pass")
        assert ctx.has_code is True
        assert ctx.has_math is False

    def test_math_detection(self) -> None:
        ctx = build_routing_context("solve the integral of x^2")
        assert ctx.has_math is True
        assert ctx.has_code is False

    def test_length(self) -> None:
        ctx = build_routing_context("Hi")
        assert ctx.query_length == 2

    def test_urgency_default(self) -> None:
        ctx = build_routing_context("test")
        assert ctx.urgency == 0.5


class TestHeuristicRouter:
    def test_short_query_prefers_small(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "large", "coder"],
        )
        ctx = RoutingContext(query="Hi", query_length=2)
        assert router.select_model(ctx) == "small"

    def test_code_prefers_coder(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "large", "coder"],
        )
        ctx = RoutingContext(
            query="def foo():",
            query_length=10,
            has_code=True,
        )
        assert router.select_model(ctx) == "coder"

    def test_math_prefers_large(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "large", "coder"],
        )
        ctx = RoutingContext(
            query="solve x",
            query_length=7,
            has_math=True,
        )
        assert router.select_model(ctx) == "large"

    def test_high_complexity_prefers_large(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "large", "coder"],
        )
        ctx = RoutingContext(query="x" * 501, query_length=501, complexity_score=0.7)
        assert router.select_model(ctx) == "large"

    def test_high_urgency_overrides_to_small(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "large", "coder"],
        )
        ctx = RoutingContext(
            query="x" * 501,
            query_length=501,
            urgency=0.9,
        )
        assert router.select_model(ctx) == "small"

    def test_fallback_chain(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "large"],
            default_model="large",
            fallback_model="small",
        )
        # Medium complexity, no code/math, no reasoning → falls to default
        ctx = RoutingContext(
            query="Tell me about cats",
            query_length=60,
            complexity_score=0.35,
        )
        assert router.select_model(ctx) == "large"

    def test_no_available_models(self) -> None:
        router = HeuristicRouter(
            available_models=[],
            default_model="fallback-model",
        )
        ctx = RoutingContext(query="test", query_length=4)
        assert router.select_model(ctx) == "fallback-model"

    def test_reasoning_keywords_prefer_large(self) -> None:
        _register_models()
        router = HeuristicRouter(available_models=["small", "large"])
        query = (
            "Please explain step by step how the process"
            " of photosynthesis works in plants"
        )
        ctx = build_routing_context(query)
        assert router.select_model(ctx) == "large"

    def test_code_without_coder_falls_to_large(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "large"],
        )
        ctx = RoutingContext(
            query="def foo():",
            query_length=10,
            has_code=True,
        )
        assert router.select_model(ctx) == "large"
