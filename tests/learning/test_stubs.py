"""Tests for learning ABC stubs."""

from __future__ import annotations

from friday_ai.learning._stubs import RoutingContext


class TestRoutingContext:
    def test_defaults(self) -> None:
        ctx = RoutingContext()
        assert ctx.query == ""
        assert ctx.query_length == 0
        assert ctx.has_code is False
        assert ctx.has_math is False
        assert ctx.language == "en"
        assert ctx.urgency == 0.5
        assert ctx.metadata == {}

    def test_custom_values(self) -> None:
        ctx = RoutingContext(
            query="def foo():",
            query_length=10,
            has_code=True,
            has_math=False,
            language="py",
            urgency=0.9,
            metadata={"key": "val"},
        )
        assert ctx.query == "def foo():"
        assert ctx.query_length == 10
        assert ctx.has_code is True
        assert ctx.language == "py"
        assert ctx.urgency == 0.9
        assert ctx.metadata == {"key": "val"}
