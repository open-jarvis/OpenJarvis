"""Tests for the calculator tool."""

from __future__ import annotations

import math

import pytest

from friday_ai.tools.calculator import CalculatorTool, safe_eval


class TestSafeEval:
    def test_addition(self):
        assert safe_eval("2 + 3") == 5

    def test_subtraction(self):
        assert safe_eval("10 - 3") == 7

    def test_multiplication(self):
        assert safe_eval("4 * 5") == 20

    def test_division(self):
        assert safe_eval("10 / 4") == 2.5

    def test_floor_division(self):
        assert safe_eval("floor(10/3)") == 3

    def test_modulo(self):
        assert safe_eval("10 % 3") == 1

    def test_power(self):
        assert safe_eval("2^10") == 1024

    def test_negative(self):
        assert safe_eval("-5 + 3") == -2

    def test_nested_expressions(self):
        assert safe_eval("(2 + 3) * (4 - 1)") == 15

    def test_sqrt(self):
        assert safe_eval("sqrt(16)") == 4.0

    def test_log(self):
        assert abs(safe_eval("ln(e)") - 1.0) < 1e-10

    def test_pi_constant(self):
        assert abs(safe_eval("pi") - math.pi) < 1e-10

    def test_trig(self):
        assert abs(safe_eval("sin(0)")) < 1e-10
        assert abs(safe_eval("cos(0)") - 1.0) < 1e-10

    def test_division_by_zero(self):
        # meval returns infinity for division by zero
        assert safe_eval("1 / 0") == math.inf

    def test_syntax_error(self):
        with pytest.raises(ValueError):
            safe_eval("2 +")

    def test_unsupported_string_constant(self):
        with pytest.raises(ValueError):
            safe_eval("'hello'")

    def test_unknown_function(self):
        with pytest.raises(ValueError, match="Unknown function"):
            safe_eval("exec(1)")

    def test_unknown_variable(self):
        with pytest.raises(ValueError, match="unknown variable"):
            safe_eval("x + 1")


class TestCalculatorTool:
    def test_spec(self):
        tool = CalculatorTool()
        assert tool.spec.name == "calculator"
        assert tool.spec.category == "math"

    def test_basic_math(self):
        tool = CalculatorTool()
        result = tool.execute(expression="2 + 3 * 4")
        assert result.success is True
        assert result.content == "14.0"

    def test_empty_expression(self):
        tool = CalculatorTool()
        result = tool.execute(expression="")
        assert result.success is False

    def test_no_expression(self):
        tool = CalculatorTool()
        result = tool.execute()
        assert result.success is False

    def test_division_by_zero_error(self):
        tool = CalculatorTool()
        result = tool.execute(expression="1/0")
        # meval returns infinity for division by zero (not an error)
        assert result.success is True
        assert result.content == "inf"

    def test_invalid_expression_error(self):
        tool = CalculatorTool()
        result = tool.execute(expression="import os")
        assert result.success is False

    def test_openai_function_format(self):
        tool = CalculatorTool()
        fn = tool.to_openai_function()
        assert fn["function"]["name"] == "calculator"
        assert "expression" in fn["function"]["parameters"]["properties"]
