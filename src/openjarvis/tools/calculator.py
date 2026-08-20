"""Calculator tool — safe math evaluation via ``ast`` module."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Allowed binary operators
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# Allowed unary operators
_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Allowed math functions (safe subset)
_MATH_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "ln": math.log,  # alias: ln(x) == log(x)
    "log10": math.log10,
    "log2": math.log2,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
    "ceil": math.ceil,
    "floor": math.floor,
}


def _safe_eval_node(node: ast.AST) -> Any:
    """Recursively evaluate an AST node using only whitelisted operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BINOPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        return _BINOPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARYOPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval_node(node.operand)
        return _UNARYOPS[op_type](operand)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        fname = node.func.id
        if fname not in _MATH_FUNCS:
            raise ValueError(f"Unknown function: {fname}")
        func = _MATH_FUNCS[fname]
        args = [_safe_eval_node(a) for a in node.args]
        return func(*args)
    if isinstance(node, ast.Name):
        name = node.id
        if name in _MATH_FUNCS:
            val = _MATH_FUNCS[name]
            if isinstance(val, (int, float)):
                return val
        raise ValueError(f"unknown variable: {name}")
    raise ValueError(f"Unsupported expression type: {type(node).__name__}")


def safe_eval(expression: str) -> float:
    """Evaluate a math expression safely — Rust backend with Python fallback."""
    try:
        from openjarvis._rust_bridge import get_rust_module

        _rust = get_rust_module()
        return float(_rust.CalculatorTool().execute(expression))
    except ImportError:
        import ast as _ast

        # Support ^ as the power operator (common math/calculator notation).
        expression = expression.replace("^", "**")
        try:
            tree = _ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Syntax error in expression: {exc}") from exc
        try:
            return float(_safe_eval_node(tree.body))
        except ZeroDivisionError:
            return math.inf


@ToolRegistry.register("calculator")
class CalculatorTool(BaseTool):
    """Safe math calculator using AST-based evaluation."""

    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description=(
                "Evaluate a mathematical expression safely."
                " Supports arithmetic, math functions"
                " (sqrt, log, sin, cos), and constants."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "Math expression to evaluate (e.g. '2+3*4', 'sqrt(16)')"
                        ),
                    },
                },
                "required": ["expression"],
            },
            category="math",
        )

    def execute(self, **params: Any) -> ToolResult:
        expression = params.get("expression", "")
        if not expression:
            return ToolResult(
                tool_name="calculator",
                content="No expression provided.",
                success=False,
            )
        try:
            result = safe_eval(expression)
            return ToolResult(
                tool_name="calculator",
                content=str(result),
                success=True,
            )
        except ZeroDivisionError:
            return ToolResult(
                tool_name="calculator",
                content="Error: division by zero",
                success=False,
            )
        except (ValueError, SyntaxError, TypeError) as exc:
            return ToolResult(
                tool_name="calculator",
                content=f"Error: {exc}",
                success=False,
            )


__all__ = ["CalculatorTool", "safe_eval"]
