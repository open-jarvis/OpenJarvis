"""Tests for router behavior with the extended model catalog."""

from __future__ import annotations

import pytest

from openjarvis.intelligence.model_catalog import register_builtin_models
from openjarvis.learning._stubs import RoutingContext
from openjarvis.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)

# New local model keys for testing
NEW_LOCAL_MODELS = [
    "gpt-oss:120b",  # 117B total, 5.1B active, MoE
    "qwen3:8b",  # 8.2B, dense
    "glm-4.7-flash",  # 30B total, 3.0B active, MoE
    "trinity-mini",  # 26B total, 3.0B active, MoE
]

# Cloud model keys
CLOUD_MODELS = [
    "gpt-5-mini",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "gemini-2.5-pro",
    "gemini-3-flash",
]


def _setup_models() -> None:
    """Register builtin models needed for the tests."""
    register_builtin_models()


class TestRouterWithNewModels:
    """Router behavior when using the new local models."""

    def test_short_query_routes_to_smallest(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
        )
        ctx = RoutingContext(query="hi", query_length=2)
        selected = router.select_model(ctx)
        assert selected == "qwen3:8b"

    def test_code_query_routes_to_largest(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
        )
        ctx = RoutingContext(
            query="def merge_sort(arr):",
            query_length=22,
            has_code=True,
        )
        selected = router.select_model(ctx)
        assert selected == "gpt-oss:120b"

    def test_code_query_with_coder_available(self) -> None:
        _setup_models()
        models = NEW_LOCAL_MODELS + ["deepseek-coder-v2:16b"]
        router = HeuristicRouter(available_models=models)
        ctx = RoutingContext(
            query="import numpy as np",
            query_length=18,
            has_code=True,
        )
        selected = router.select_model(ctx)
        assert selected == "deepseek-coder-v2:16b"

    def test_math_query_routes_to_largest(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
        )
        ctx = RoutingContext(
            query="solve the integral of x^2 dx",
            query_length=29,
            has_math=True,
        )
        selected = router.select_model(ctx)
        assert selected == "gpt-oss:120b"

    def test_high_complexity_routes_to_largest(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
        )
        ctx = RoutingContext(query="x" * 501, query_length=501, complexity_score=0.7)
        selected = router.select_model(ctx)
        assert selected == "gpt-oss:120b"

    def test_high_urgency_routes_to_smallest(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
        )
        ctx = RoutingContext(
            query="solve the integral of x^2",
            query_length=25,
            has_math=True,
            urgency=0.9,
        )
        selected = router.select_model(ctx)
        assert selected == "qwen3:8b"

    def test_reasoning_query_routes_to_largest(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
        )
        ctx = build_routing_context(
            "Please explain step by step how neural networks learn"
        )
        selected = router.select_model(ctx)
        assert selected == "gpt-oss:120b"

    def test_medium_query_uses_default(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
            default_model="glm-4.7-flash",
        )
        ctx = RoutingContext(
            query="Tell me about the weather today",
            query_length=60,
            complexity_score=0.35,
        )
        selected = router.select_model(ctx)
        assert selected == "glm-4.7-flash"


class TestRouterCloudFallback:
    """Router behavior when only cloud models are available."""

    def test_no_local_falls_to_cloud(self) -> None:
        _setup_models()
        router = HeuristicRouter(available_models=CLOUD_MODELS)
        ctx = RoutingContext(query="hi", query_length=2)
        selected = router.select_model(ctx)
        assert selected in CLOUD_MODELS

    def test_cloud_model_selection_with_math(self) -> None:
        _setup_models()
        router = HeuristicRouter(available_models=CLOUD_MODELS)
        ctx = RoutingContext(
            query="solve x",
            query_length=7,
            has_math=True,
        )
        selected = router.select_model(ctx)
        assert selected in CLOUD_MODELS

    def test_empty_models_returns_fallback(self) -> None:
        router = HeuristicRouter(
            available_models=[],
            fallback_model="gpt-5-mini",
        )
        ctx = RoutingContext(query="hello", query_length=5)
        assert router.select_model(ctx) == "gpt-5-mini"


class TestRouterParameterized:
    """Parametrized tests for model/query combinations."""

    @pytest.mark.parametrize(
        "query,expected_is_largest",
        [
            ("hi", False),
            ("solve the integral of sin(x)", True),
            ("def foo(): pass", True),
            (
                "Explain step by step how to solve the integral of x^2 "
                "and then write code to compute the derivative",
                True,
            ),
        ],
    )
    def test_query_type_selects_expected_size(
        self,
        query: str,
        expected_is_largest: bool,
    ) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
        )
        ctx = build_routing_context(query)
        selected = router.select_model(ctx)
        if expected_is_largest:
            assert selected == "gpt-oss:120b"
        else:
            assert selected == "qwen3:8b"

    @pytest.mark.parametrize("model_id", NEW_LOCAL_MODELS)
    def test_single_model_always_returns_it(
        self,
        model_id: str,
    ) -> None:
        _setup_models()
        router = HeuristicRouter(available_models=[model_id])
        ctx = RoutingContext(
            query="hello world",
            query_length=11,
        )
        assert router.select_model(ctx) == model_id

    @pytest.mark.parametrize("urgency", [0.85, 0.9, 1.0])
    def test_high_urgency_always_smallest(
        self,
        urgency: float,
    ) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=NEW_LOCAL_MODELS,
        )
        ctx = RoutingContext(
            query="complex reasoning task",
            query_length=23,
            has_math=True,
            urgency=urgency,
        )
        assert router.select_model(ctx) == "qwen3:8b"
