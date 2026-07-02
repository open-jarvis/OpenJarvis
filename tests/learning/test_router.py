"""Tests for the heuristic model router (canonical location)."""

from __future__ import annotations

from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import ModelSpec
from openjarvis.learning._stubs import RoutingContext
from openjarvis.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
    escalation_chain_for_lane,
    explain_route,
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
    ModelRegistry.register_value(
        "free",
        ModelSpec(
            model_id="openrouter/free",
            name="OpenRouter Free",
            parameter_count_b=0.0,
            context_length=131072,
            supported_engines=("cloud",),
            provider="openrouter",
        ),
    )
    ModelRegistry.register_value(
        "vision",
        ModelSpec(
            model_id="qwen/qwen3-vl-32b-instruct",
            name="Qwen Vision",
            parameter_count_b=32.0,
            context_length=131072,
            supported_engines=("cloud",),
            provider="openrouter",
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

    def test_task_class_detection_for_code(self) -> None:
        ctx = build_routing_context("please write a python function and tests")
        assert ctx.task_class in {"code-simple", "test-generation"}
        assert ctx.task_class_confidence > 0.0

    def test_vision_detection(self) -> None:
        ctx = build_routing_context("describe this screenshot")
        assert ctx.vision_required is True


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

    def test_router_lane_prefers_small_control_model(self) -> None:
        _register_models()
        router = HeuristicRouter(available_models=["small", "large"])
        ctx = RoutingContext(
            query="classify this ticket",
            query_length=20,
            task_class="classify",
        )
        assert router.select_model(ctx) == "small"

    def test_code_lane_prefers_coder(self) -> None:
        _register_models()
        router = HeuristicRouter(available_models=["small", "large", "coder"])
        ctx = RoutingContext(
            query="write a patch",
            query_length=20,
            task_class="code-simple",
        )
        assert router.select_model(ctx) == "coder"

    def test_free_fallback_lane_prefers_openrouter_free(self) -> None:
        _register_models()
        router = HeuristicRouter(available_models=["small", "openrouter/free", "large"])
        ctx = RoutingContext(
            query="cheap low-stakes fallback",
            query_length=24,
            task_class="summarize",
            budget_sensitivity="high",
            risk_level="low",
        )
        assert router.select_model(ctx) == "openrouter/free"

    def test_long_context_lane_prefers_larger_model(self) -> None:
        _register_models()
        router = HeuristicRouter(available_models=["small", "large"])
        ctx = RoutingContext(
            query="synthesize these long documents",
            query_length=2000,
            task_class="synthesis",
            complexity_score=0.7,
            estimated_context_tokens=8000,
        )
        assert router.select_model(ctx) == "large"

    def test_vision_lane_prefers_vision_model(self) -> None:
        _register_models()
        router = HeuristicRouter(
            available_models=["small", "qwen/qwen3-vl-32b-instruct", "large"]
        )
        ctx = RoutingContext(
            query="describe this screenshot",
            query_length=24,
            task_class="source-reading",
            vision_required=True,
        )
        assert router.select_model(ctx) == "qwen/qwen3-vl-32b-instruct"

    def test_escalation_chain_for_code_lane(self) -> None:
        chain = escalation_chain_for_lane("code_specialist")
        assert chain == [
            "code_specialist",
            "premium_workhorse",
            "frontier_premium",
        ]

    def test_explain_route_exposes_candidates_and_escalation(self) -> None:
        _register_models()
        decision = explain_route(
            RoutingContext(
                query="write a patch",
                query_length=20,
                task_class="code-simple",
            ),
            available_models=["small", "coder", "large"],
        )
        assert decision.lane == "code_specialist"
        assert decision.model == "coder"
        assert "coder" in decision.candidate_models
        assert decision.escalation_chain[0] == "code_specialist"
