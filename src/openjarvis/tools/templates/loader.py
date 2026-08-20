"""Template loader — dynamically construct BaseTool from TOML definitions."""

from __future__ import annotations

import ast
import json
import logging
import operator
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


# --- Safe expression evaluation for ``python``-action templates -----------
# Templates may embed a Python expression (e.g. ``"str(float(value))"``).
# A bare ``eval()`` — even with a restricted ``__builtins__`` — is trivially
# escapable via attribute walks such as
# ``str.__class__.__mro__[-1].__subclasses__()``, which reach
# ``object.__subclasses__()`` and from there arbitrary code execution.
#
# Instead of calling ``eval()`` at all, we parse the expression and walk the
# AST with a small interpreter that implements only an explicit allowlist of
# node types. Attribute access, lambdas, comprehensions, dunder names, and
# calls to anything other than the whitelisted builtins simply have no
# implementation and raise ``ValueError`` — the escape vectors are
# unreachable by construction.

_SAFE_EVAL_FUNCS: Dict[str, Callable[..., Any]] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sorted": sorted,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
}

_BIN_OPS: Dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: Dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
    ast.Invert: operator.invert,
}

_CMP_OPS: Dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _eval_node(node: ast.AST, names: Dict[str, Any]) -> Any:
    """Recursively evaluate a single whitelisted AST node."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, names)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id.startswith("__"):
            raise ValueError(f"disallowed name: {node.id}")
        if node.id in names:
            return names[node.id]
        if node.id in _SAFE_EVAL_FUNCS:
            return _SAFE_EVAL_FUNCS[node.id]
        raise ValueError(f"unknown name: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](
            _eval_node(node.left, names), _eval_node(node.right, names)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand, names))
    if isinstance(node, ast.BoolOp):
        result: Any = isinstance(node.op, ast.And)
        for value in node.values:
            result = _eval_node(value, names)
            if isinstance(node.op, ast.And) and not result:
                return result
            if isinstance(node.op, ast.Or) and result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, names)
        for op, comparator in zip(node.ops, node.comparators):
            if type(op) not in _CMP_OPS:
                raise ValueError(f"disallowed comparison: {type(op).__name__}")
            right = _eval_node(comparator, names)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        branch = node.body if _eval_node(node.test, names) else node.orelse
        return _eval_node(branch, names)
    if isinstance(node, ast.Call):
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_EVAL_FUNCS:
            raise ValueError("only calls to whitelisted builtins are allowed")
        func = _SAFE_EVAL_FUNCS[node.func.id]
        return func(*[_eval_node(a, names) for a in node.args])
    if isinstance(node, ast.Subscript):
        return _eval_node(node.value, names)[_eval_node(node.slice, names)]
    if isinstance(node, ast.Slice):
        return slice(
            _eval_node(node.lower, names) if node.lower else None,
            _eval_node(node.upper, names) if node.upper else None,
            _eval_node(node.step, names) if node.step else None,
        )
    if isinstance(node, ast.List):
        return [_eval_node(e, names) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, names) for e in node.elts)
    if isinstance(node, ast.Set):
        return {_eval_node(e, names) for e in node.elts}
    if isinstance(node, ast.Dict):
        return {
            _eval_node(k, names): _eval_node(v, names)
            for k, v in zip(node.keys, node.values)
        }
    raise ValueError(f"disallowed expression element: {type(node).__name__}")


def safe_eval_expr(expr: str, names: Dict[str, Any]) -> Any:
    """Safely evaluate a template ``python``-action expression.

    Parses *expr* and interprets it against the allowlist in
    :func:`_eval_node`. No ``eval``/``exec`` is used, and the only callables
    reachable are :data:`_SAFE_EVAL_FUNCS` plus the supplied *names* (the tool
    parameters). Raises ``ValueError`` / ``SyntaxError`` on anything unsafe.
    """
    return _eval_node(ast.parse(expr, mode="eval"), names)


class ToolTemplate(BaseTool):
    """A tool dynamically constructed from a TOML template definition."""

    tool_id: str

    def __init__(self, template_data: Dict[str, Any]) -> None:
        self._data = template_data
        self.tool_id = template_data.get("name", "template")
        self._name = template_data.get("name", "template")
        self._description = template_data.get("description", "")
        self._parameters = template_data.get("parameters", {})
        self._action = template_data.get("action", {})

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description=self._description,
            parameters=self._parameters,
            category="template",
            metadata={"template": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        action_type = self._action.get("type", "python")

        try:
            if action_type == "python":
                return self._execute_python(params)
            elif action_type == "shell":
                return self._execute_shell(params)
            elif action_type == "transform":
                return self._execute_transform(params)
            else:
                return ToolResult(
                    tool_name=self._name,
                    content=f"Unknown action type: {action_type}",
                    success=False,
                )
        except Exception as exc:
            return ToolResult(
                tool_name=self._name,
                content=f"Template execution error: {exc}",
                success=False,
            )

    def _execute_python(self, params: Dict[str, Any]) -> ToolResult:
        """Execute a Python expression."""
        expr = self._action.get("expression", "")
        if not expr:
            return ToolResult(
                tool_name=self._name,
                content="No expression defined.",
                success=False,
            )
        try:
            result = safe_eval_expr(expr, params)
        except (ValueError, SyntaxError) as exc:
            return ToolResult(
                tool_name=self._name,
                content=f"Rejected unsafe or invalid expression: {exc}",
                success=False,
            )
        return ToolResult(
            tool_name=self._name,
            content=str(result),
            success=True,
        )

    def _execute_shell(self, params: Dict[str, Any]) -> ToolResult:
        """Execute a shell command (requires code:execute capability)."""
        cmd_template = self._action.get("command", "")
        if not cmd_template:
            return ToolResult(
                tool_name=self._name,
                content="No command defined.",
                success=False,
            )
        # Tokenize the FIXED template command first, then substitute params
        # into individual argv elements and run WITHOUT a shell. A parameter
        # value such as ``; rm -rf ~`` or ``$(curl evil)`` becomes a single
        # literal argument rather than shell syntax, so it cannot inject.
        try:
            tokens = shlex.split(cmd_template)
        except ValueError as exc:
            return ToolResult(
                tool_name=self._name,
                content=f"Invalid command template: {exc}",
                success=False,
            )
        argv = [self._substitute(token, params) for token in tokens]
        if not argv:
            return ToolResult(
                tool_name=self._name,
                content="Empty command.",
                success=False,
            )
        result = subprocess.run(  # noqa: S603
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or result.stderr
        return ToolResult(
            tool_name=self._name,
            content=output.strip(),
            success=result.returncode == 0,
        )

    @staticmethod
    def _substitute(token: str, params: Dict[str, Any]) -> str:
        """Replace ``{key}`` placeholders in a single argv token."""
        for key, val in params.items():
            token = token.replace(f"{{{key}}}", str(val))
        return token

    def _execute_transform(self, params: Dict[str, Any]) -> ToolResult:
        """Execute a data transformation."""
        transform = self._action.get("transform", "identity")
        input_val = params.get("input", "")
        if transform == "upper":
            return ToolResult(
                tool_name=self._name,
                content=str(input_val).upper(),
                success=True,
            )
        elif transform == "lower":
            return ToolResult(
                tool_name=self._name,
                content=str(input_val).lower(),
                success=True,
            )
        elif transform == "length":
            return ToolResult(
                tool_name=self._name,
                content=str(len(str(input_val))),
                success=True,
            )
        elif transform == "reverse":
            return ToolResult(
                tool_name=self._name,
                content=str(input_val)[::-1],
                success=True,
            )
        elif transform == "json_pretty":
            try:
                parsed = json.loads(str(input_val))
                return ToolResult(
                    tool_name=self._name,
                    content=json.dumps(
                        parsed,
                        indent=2,
                    ),
                    success=True,
                )
            except json.JSONDecodeError as exc:
                return ToolResult(
                    tool_name=self._name,
                    content=f"Invalid JSON: {exc}",
                    success=False,
                )
        else:
            return ToolResult(
                tool_name=self._name,
                content=str(input_val),
                success=True,
            )


def load_template(path: str | Path) -> ToolTemplate:
    """Load a single tool template from a TOML file."""
    path = Path(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    tool_data = data.get("tool", data)
    return ToolTemplate(tool_data)


def discover_templates(
    directory: Optional[str | Path] = None,
) -> List[ToolTemplate]:
    """Discover all TOML templates in a directory."""
    if directory is None:
        directory = Path(__file__).parent / "builtin"
    directory = Path(directory)
    if not directory.exists():
        return []
    templates = []
    for path in sorted(directory.glob("*.toml")):
        try:
            templates.append(load_template(path))
        except Exception as exc:
            logger.debug("Skipping unparseable template %s: %s", path, exc)
    return templates


__all__ = ["ToolTemplate", "discover_templates", "load_template"]
