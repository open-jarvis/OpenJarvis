"""Tests for query complexity analyzer."""

from __future__ import annotations

from openjarvis.learning.routing.complexity import (
    ComplexityQueryAnalyzer,
    ComplexityResult,
    adjust_tokens_for_model,
    is_thinking_model,
    score_complexity,
)


class TestScoreComplexity:
    def test_trivial_query(self) -> None:
        result = score_complexity("Hi")
        assert result.tier == "trivial"
        assert result.score < 0.15

    def test_simple_query(self) -> None:
        result = score_complexity("What is the capital of France?")
        assert result.tier in ("trivial", "simple")
        assert result.score < 0.30

    def test_code_signal(self) -> None:
        result = score_complexity("def hello():\n    return 'world'")
        assert result.signals["has_code"] is True
        assert result.score > 0.0

    def test_math_signal(self) -> None:
        result = score_complexity("Solve the integral of x^2 dx")
        assert result.signals["has_math"] is True
        assert result.score > 0.0

    def test_code_and_math_gives_high_domain(self) -> None:
        query = "```python\nimport numpy\n```\nSolve the integral of x^2"
        result = score_complexity(query)
        assert result.signals["has_code"] is True
        assert result.signals["has_math"] is True
        assert result.signals["domain"] == 1.0

    def test_reasoning_signal(self) -> None:
        result = score_complexity("Explain why the sky is blue step by step")
        assert result.signals["has_reasoning"] is True

    def test_multi_step_signal(self) -> None:
        result = score_complexity("First do X, then do Y, then do Z")
        assert result.signals["has_multi_step"] is True

    def test_reasoning_and_multi_step_combined(self) -> None:
        result = score_complexity(
            "Explain why X works, then analyze Y, then compare them"
        )
        assert result.signals["has_reasoning"] is True
        assert result.signals["has_multi_step"] is True
        assert result.signals["reasoning"] == 1.0

    def test_multi_part_questions(self) -> None:
        query = "What is X? What is Y? What is Z? What is W?"
        result = score_complexity(query)
        assert result.signals["n_questions"] == 4
        assert result.signals["multi_part"] == 1.0

    def test_creative_signal(self) -> None:
        result = score_complexity("Write an essay about climate change")
        assert result.signals["has_creative"] is True

    def test_very_complex_query(self) -> None:
        query = (
            "Explain step by step how to solve the integral of x^2, "
            "then write Python code to compute it numerically. "
            "1. Derive the analytical solution\n"
            "2. Implement numerical integration\n"
            "3. Compare the results and analyze the error"
        )
        result = score_complexity(query)
        assert result.tier in ("complex", "very_complex")
        assert result.score >= 0.55

    def test_score_clamped_to_unit_interval(self) -> None:
        result = score_complexity("x" * 2000)
        assert 0.0 <= result.score <= 1.0

    def test_result_type(self) -> None:
        result = score_complexity("hello")
        assert isinstance(result, ComplexityResult)
        assert isinstance(result.score, float)
        assert isinstance(result.tier, str)
        assert isinstance(result.suggested_max_tokens, int)
        assert isinstance(result.signals, dict)

    def test_token_tiers_increase_with_complexity(self) -> None:
        trivial = score_complexity("Hi")
        complex_ = score_complexity(
            "Explain step by step how to solve the integral of x^2 "
            "and write code to compute the derivative of the matrix equation"
        )
        assert complex_.suggested_max_tokens >= trivial.suggested_max_tokens

    def test_subtask_counting(self) -> None:
        query = "1. First task\n2. Second task\n- Bullet item"
        result = score_complexity(query)
        assert result.signals["n_subtasks"] == 3


class TestIsThinkingModel:
    def test_deepseek_r1(self) -> None:
        assert is_thinking_model("deepseek-r1-32b") is True

    def test_o1_model(self) -> None:
        assert is_thinking_model("o1-preview") is True

    def test_o3_model(self) -> None:
        assert is_thinking_model("o3-mini") is True

    def test_qwq(self) -> None:
        assert is_thinking_model("qwq-32b") is True

    def test_regular_model(self) -> None:
        assert is_thinking_model("llama-3.1-8b") is False

    def test_gpt4(self) -> None:
        assert is_thinking_model("gpt-4o") is False


class TestAdjustTokensForModel:
    def test_thinking_model_doubles(self) -> None:
        assert adjust_tokens_for_model(1024, "deepseek-r1-32b") == 2048

    def test_regular_model_unchanged(self) -> None:
        assert adjust_tokens_for_model(1024, "llama-3.1-8b") == 1024

    def test_no_model_unchanged(self) -> None:
        assert adjust_tokens_for_model(1024) == 1024

    def test_none_model_unchanged(self) -> None:
        assert adjust_tokens_for_model(1024, None) == 1024


class TestComplexityQueryAnalyzer:
    def test_returns_routing_context(self) -> None:
        analyzer = ComplexityQueryAnalyzer()
        ctx = analyzer.analyze("Hello world")
        assert ctx.query == "Hello world"
        assert ctx.query_length == len("Hello world")

    def test_complexity_score_populated(self) -> None:
        analyzer = ComplexityQueryAnalyzer()
        ctx = analyzer.analyze("Explain step by step how photosynthesis works")
        assert ctx.complexity_score > 0.0
        assert ctx.has_reasoning is True

    def test_code_detection(self) -> None:
        analyzer = ComplexityQueryAnalyzer()
        ctx = analyzer.analyze("def foo(): pass")
        assert ctx.has_code is True

    def test_math_detection(self) -> None:
        analyzer = ComplexityQueryAnalyzer()
        ctx = analyzer.analyze("solve the equation x^2 = 4")
        assert ctx.has_math is True

    def test_urgency_passthrough(self) -> None:
        analyzer = ComplexityQueryAnalyzer()
        ctx = analyzer.analyze("test", urgency=0.9)
        assert ctx.urgency == 0.9

    def test_invalid_urgency_defaults(self) -> None:
        analyzer = ComplexityQueryAnalyzer()
        ctx = analyzer.analyze("test", urgency="invalid")
        assert ctx.urgency == 0.5

    def test_thinking_model_adjusts_tokens(self) -> None:
        analyzer = ComplexityQueryAnalyzer()
        ctx_normal = analyzer.analyze("Hello", model="llama-3.1-8b")
        ctx_thinking = analyzer.analyze("Hello", model="deepseek-r1-32b")
        assert ctx_thinking.suggested_max_tokens == ctx_normal.suggested_max_tokens * 2

    def test_metadata_contains_tier(self) -> None:
        analyzer = ComplexityQueryAnalyzer()
        ctx = analyzer.analyze("Hi")
        assert "complexity_tier" in ctx.metadata
        assert "signals" in ctx.metadata
