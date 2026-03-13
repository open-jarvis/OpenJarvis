"""Tests for classify_query utility."""

from __future__ import annotations

from openjarvis.learning.routing._utils import classify_query


class TestClassifyQuery:
    def test_code_detection(self) -> None:
        assert classify_query("def hello(): pass") == "code"
        assert classify_query("```python\nprint()```") == "code"
        assert classify_query("import os") == "code"

    def test_math_detection(self) -> None:
        assert classify_query("solve this equation for x") == "math"
        assert classify_query("compute the integral") == "math"

    def test_short(self) -> None:
        assert classify_query("hello") == "short"
        assert classify_query("what time is it?") == "short"

    def test_long(self) -> None:
        assert classify_query("a" * 501) == "long"

    def test_general(self) -> None:
        q = "Tell me about the history of artificial intelligence research"
        assert classify_query(q) == "general"
