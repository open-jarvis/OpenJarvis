"""Security regression tests for the tool-template loader (issue #216).

`python`-action templates must not be able to escape the expression sandbox
(no attribute walks reaching `object.__subclasses__()`), and `shell`-action
templates must not allow command injection through parameter substitution.
"""

from __future__ import annotations

import os

import pytest

from openjarvis.tools.templates.loader import (
    ToolTemplate,
    discover_templates,
    safe_eval_expr,
)

# Expressions that previously reached arbitrary code execution via the
# sandbox escape, plus other dangerous constructs. All must raise.
ESCAPE_EXPRESSIONS = [
    "str.__class__.__mro__[-1].__subclasses__()",
    "().__class__.__bases__[0].__subclasses__()",
    "__import__('os').system('id')",
    "[c for c in ().__class__.__base__.__subclasses__()]",
    "(lambda: 1)()",
    "open('/etc/passwd').read()",
    "globals()",
    "().__class__",
]


@pytest.mark.parametrize("expr", ESCAPE_EXPRESSIONS)
def test_escape_expressions_are_rejected(expr: str) -> None:
    with pytest.raises((ValueError, SyntaxError)):
        safe_eval_expr(expr, {})


@pytest.mark.parametrize(
    ("expr", "names", "expected"),
    [
        ("str(float(value))", {"value": 3}, "3.0"),
        ("str(input)", {"input": "hi"}, "hi"),
        ("str(input) if input else 'no input'", {"input": ""}, "no input"),
        ("len(input) * 2 + 1", {"input": "abcd"}, 9),
        ("sorted(input)[0]", {"input": [3, 1, 2]}, 1),
        ("max(a, b)", {"a": 5, "b": 9}, 9),
        ("input[1:3]", {"input": "abcdef"}, "bc"),
    ],
)
def test_legitimate_expressions_still_work(expr, names, expected) -> None:
    assert safe_eval_expr(expr, names) == expected


def test_python_action_rejects_escape_via_execute() -> None:
    tmpl = ToolTemplate(
        {
            "name": "evil",
            "action": {
                "type": "python",
                "expression": "str.__class__.__mro__[-1].__subclasses__()",
            },
        }
    )
    result = tmpl.execute()
    assert result.success is False
    assert "unsafe" in result.content.lower() or "disallowed" in result.content.lower()


def test_shell_action_neutralizes_injection(tmp_path) -> None:
    """A `;`-style injection in a parameter must not run as shell syntax."""
    marker = tmp_path / "pwned"
    tmpl = ToolTemplate(
        {
            "name": "echoer",
            "action": {"type": "shell", "command": "echo {msg}"},
        }
    )
    result = tmpl.execute(msg=f"hello; touch {marker}")
    # The injected command text is echoed back literally, not executed.
    assert "hello" in result.content
    assert not marker.exists(), "command injection executed — marker was created"


def test_shell_action_passes_values_as_single_argument() -> None:
    """Whitespace in a value stays one argv element (no word-splitting)."""
    tmpl = ToolTemplate(
        {
            "name": "echoer",
            "action": {"type": "shell", "command": "echo {msg}"},
        }
    )
    result = tmpl.execute(msg="a b c")
    assert result.content == "a b c"


def test_builtin_templates_still_load_and_run() -> None:
    """Every shipped builtin template loads and its action executes safely."""
    templates = discover_templates()
    assert templates, "no builtin templates discovered"
    for tmpl in templates:
        # Exercise with a representative input; should not raise.
        result = tmpl.execute(input="hello", value=1.5, text="hi")
        assert result.tool_name == tmpl.spec.name


def test_shell_action_command_substitution_is_inert(tmp_path) -> None:
    """Backtick / command-substitution payloads are inert too."""
    marker = tmp_path / "sub"
    tmpl = ToolTemplate(
        {
            "name": "echoer",
            "action": {"type": "shell", "command": "echo {msg}"},
        }
    )
    tmpl.execute(msg=f"$(touch {marker})")
    assert not marker.exists()
    tmpl.execute(msg=f"`touch {marker}`")
    assert not marker.exists()


def test_attribute_access_unavailable_even_for_param_objects() -> None:
    """Even if a param holds a module, attribute access stays unreachable."""
    with pytest.raises((ValueError, SyntaxError)):
        safe_eval_expr("payload.__class__", {"payload": os})
