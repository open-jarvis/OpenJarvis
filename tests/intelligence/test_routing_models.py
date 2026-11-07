"""Tests for the router with model catalog via canonical imports."""

from __future__ import annotations

from friday_ai.intelligence.model_catalog import register_builtin_models
from friday_ai.learning._stubs import RoutingContext
from friday_ai.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)


def _setup_models() -> None:
    register_builtin_models()


class TestRouterWithModels:
    def test_short_query(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=["qwen3:8b", "gpt-oss:120b"],
        )
        ctx = RoutingContext(query="hi", query_length=2)
        assert router.select_model(ctx) == "qwen3:8b"

    def test_code_query(self) -> None:
        _setup_models()
        router = HeuristicRouter(
            available_models=["qwen3:8b", "gpt-oss:120b"],
        )
        ctx = build_routing_context("def merge_sort(arr):")
        assert router.select_model(ctx) == "gpt-oss:120b"
