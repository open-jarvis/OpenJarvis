"""Tests for RouterPolicy and QueryAnalyzer ABCs (canonical location)."""

from __future__ import annotations

import pytest

from openjarvis.core.types import RoutingContext
from openjarvis.learning._stubs import QueryAnalyzer, RouterPolicy
from openjarvis.learning.routing.router import DefaultQueryAnalyzer


class _DummyRouter(RouterPolicy):
    def select_model(self, context: RoutingContext) -> str:
        return "test-model"


class _DummyAnalyzer(QueryAnalyzer):
    def analyze(
        self,
        query: str,
        **kwargs: object,
    ) -> RoutingContext:
        return RoutingContext(
            query=query,
            query_length=len(query),
        )


class TestRouterPolicy:
    def test_abc_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            RouterPolicy()  # type: ignore[abstract]

    def test_concrete_implementation(self) -> None:
        router = _DummyRouter()
        ctx = RoutingContext(query="hello")
        assert router.select_model(ctx) == "test-model"


class TestQueryAnalyzer:
    def test_abc_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            QueryAnalyzer()  # type: ignore[abstract]

    def test_concrete_implementation(self) -> None:
        analyzer = _DummyAnalyzer()
        ctx = analyzer.analyze("hello world")
        assert ctx.query == "hello world"
        assert ctx.query_length == 11


class TestDefaultQueryAnalyzer:
    def test_analyze_basic(self) -> None:
        analyzer = DefaultQueryAnalyzer()
        ctx = analyzer.analyze("Hello world")
        assert ctx.query == "Hello world"
        assert ctx.query_length == 11
        assert ctx.has_code is False
        assert ctx.has_math is False

    def test_analyze_code_query(self) -> None:
        analyzer = DefaultQueryAnalyzer()
        ctx = analyzer.analyze("def hello(): pass")
        assert ctx.has_code is True

    def test_analyze_math_query(self) -> None:
        analyzer = DefaultQueryAnalyzer()
        ctx = analyzer.analyze("solve the integral of x^2")
        assert ctx.has_math is True

    def test_analyze_with_urgency(self) -> None:
        analyzer = DefaultQueryAnalyzer()
        ctx = analyzer.analyze("quick question", urgency=0.9)
        assert ctx.urgency == 0.9
