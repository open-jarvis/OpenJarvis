"""Tests for Intelligence primitive backward-compat shims."""

from __future__ import annotations

import pytest


class TestBackwardCompatShims:
    """Verify ABCs are still importable from intelligence._stubs."""

    def test_router_policy_from_intelligence(self) -> None:
        from openjarvis.intelligence._stubs import RouterPolicy

        with pytest.raises(TypeError):
            RouterPolicy()  # type: ignore[abstract]

    def test_query_analyzer_from_intelligence(self) -> None:
        from openjarvis.intelligence._stubs import QueryAnalyzer

        with pytest.raises(TypeError):
            QueryAnalyzer()  # type: ignore[abstract]

    def test_same_class_as_learning(self) -> None:
        from openjarvis.intelligence._stubs import QueryAnalyzer as IQA
        from openjarvis.intelligence._stubs import RouterPolicy as IRP
        from openjarvis.learning._stubs import QueryAnalyzer as LQA
        from openjarvis.learning._stubs import RouterPolicy as LRP

        assert IRP is LRP
        assert IQA is LQA

    def test_router_from_intelligence_module(self) -> None:
        """HeuristicRouter still importable from intelligence.router."""
        from openjarvis.intelligence.router import (
            HeuristicRouter,
            build_routing_context,
        )

        ctx = build_routing_context("hello")
        assert ctx.query == "hello"
        router = HeuristicRouter(
            available_models=[],
            default_model="m",
        )
        assert router.select_model(ctx) == "m"

    def test_default_query_analyzer_from_intelligence(
        self,
    ) -> None:
        from openjarvis.intelligence.router import (
            DefaultQueryAnalyzer,
        )

        analyzer = DefaultQueryAnalyzer()
        ctx = analyzer.analyze("Hello world")
        assert ctx.query == "Hello world"


class TestRoutingContextInCoreTypes:
    """Verify RoutingContext is accessible from core.types."""

    def test_import_from_core_types(self) -> None:
        from openjarvis.core.types import RoutingContext as RC

        ctx = RC(query="test", has_code=True)
        assert ctx.query == "test"
        assert ctx.has_code is True

    def test_backward_compat_import(self) -> None:
        from openjarvis.learning._stubs import RoutingContext as RC

        ctx = RC(query="compat")
        assert ctx.query == "compat"

    def test_router_policy_backward_compat(self) -> None:
        from openjarvis.intelligence._stubs import RouterPolicy
        from openjarvis.learning._stubs import RouterPolicy as RP

        assert RP is RouterPolicy
