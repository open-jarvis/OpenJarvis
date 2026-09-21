"""Code interpreter tool — Python execution with AST validation + hardening.

Security model (defense in depth):

1. **AST allowlist validation** (this module) rejects code *before* it runs:
   imports outside a small supported set, private-attribute walks, and calls to
   ``eval``/``exec``/``compile``/``__import__``/``open``/``getattr`` &c. This
   replaces the old substring blocklist, which was trivially bypassed (e.g.
   ``getattr(__builtins__, 'sys'+'tem')`` or a simple space: ``eval ('...')``).
2. **Isolated interpreter** — the child runs with ``-I -B -S`` (isolated mode,
   no ``.pyc``, no ``site``), a sanitized environment, and POSIX resource
   limits (CPU + address space + no new files) applied in a ``preexec_fn``.
3. **Outer sandbox** — on a server this tool should run inside the Docker
   sandbox (see ``code_interpreter_docker`` / ``deploy/docker/Dockerfile.sandbox``)
   or be disabled entirely. AST validation is a filter, not a jail: the Docker
   boundary is the real containment for untrusted code.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Keep the supported import surface deliberately small. A denylist is not
# sufficient here: otherwise an apparently harmless module can re-export a
# dangerous one (for example ``platform.os.system``), and alternate file APIs
# such as ``io.open`` remain available.
_ALLOWED_IMPORTS = frozenset({"json", "math", "time"})

# Names that must never be referenced or called (escape / IO primitives).
_BLOCKED_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
        "help",
    }
)


class UnsafeCodeError(ValueError):
    """Raised when submitted code fails AST validation."""


def _validate_ast(code: str) -> None:
    """Reject code that could escape the interpreter or perform IO.

    Raises :class:`UnsafeCodeError` (or ``SyntaxError``) on anything unsafe.
    Blocking is by *structure*, not by string matching, so obfuscation such as
    ``getattr(x, 'sys'+'tem')`` or spacing tricks cannot slip through.
    """
    tree = ast.parse(code, mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in _ALLOWED_IMPORTS:
                    raise UnsafeCodeError(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.module not in _ALLOWED_IMPORTS or any(
                alias.name == "*" for alias in node.names
            ):
                raise UnsafeCodeError(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Attribute):
            # Private attributes include both dunder escape chains and module
            # implementation details that may expose imported capabilities.
            if node.attr.startswith("_"):
                raise UnsafeCodeError(f"private attribute access '{node.attr}' blocked")
        elif isinstance(node, ast.Name):
            if node.id in _BLOCKED_NAMES:
                raise UnsafeCodeError(f"use of '{node.id}' is not allowed")
            if node.id.startswith("__") and node.id.endswith("__"):
                raise UnsafeCodeError(f"dunder name '{node.id}' is not allowed")


def _child_limits() -> None:  # pragma: no cover - POSIX-only, runs in child
    """Apply resource limits in the forked child before exec (POSIX only)."""
    import resource

    # Apply each protection independently. Some platforms expose a resource
    # constant but reject changes to it (notably RLIMIT_AS on macOS); that must
    # not prevent the remaining supported limits from being installed.
    try:
        os.setsid()
    except OSError:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    except (OSError, ValueError):
        pass
    try:
        _mem = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (_mem, _mem))
    except (OSError, ValueError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    except (OSError, ValueError):
        pass


@ToolRegistry.register("code_interpreter")
class CodeInterpreterTool(BaseTool):
    """Execute Python code after AST validation, in a hardened subprocess."""

    tool_id = "code_interpreter"

    def __init__(self, timeout: int = 30, max_output: int = 10000):
        self._timeout = timeout
        self._max_output = max_output

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="code_interpreter",
            description=(
                "Execute Python code and return the output."
                " Code is AST-validated and runs in a hardened, isolated"
                " subprocess (no imports of os/sys/subprocess/network, no"
                " file IO, no eval/exec)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute.",
                    },
                },
                "required": ["code"],
            },
            category="code",
            metadata={"structured_allow_object_text": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        code = params.get("code", "")
        if not code:
            return ToolResult(
                tool_name="code_interpreter",
                content="No code provided.",
                success=False,
            )

        # Security check — reject before running, by AST structure.
        try:
            _validate_ast(code)
        except SyntaxError as exc:
            return ToolResult(
                tool_name="code_interpreter",
                content=f"SyntaxError: {exc}",
                success=False,
            )
        except UnsafeCodeError as exc:
            return ToolResult(
                tool_name="code_interpreter",
                content=f"Blocked by code validation: {exc}",
                success=False,
            )

        # Sanitized environment — drop inherited secrets/tokens.
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
        # ``preexec_fn`` only exists / is safe on POSIX.
        preexec = _child_limits if os.name == "posix" else None

        try:
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-S", "-c", code],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=safe_env,
                cwd=os.environ.get("OPENJARVIS_CODE_CWD") or None,
                preexec_fn=preexec,  # noqa: PLW1509 - intentional child hardening
            )
            output = result.stdout
            if result.stderr:
                output += ("\n" if output else "") + result.stderr
            if len(output) > self._max_output:
                output = output[: self._max_output] + "\n... (output truncated)"
            return ToolResult(
                tool_name="code_interpreter",
                content=output or "(no output)",
                success=result.returncode == 0,
                metadata={"returncode": result.returncode},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name="code_interpreter",
                content=f"Execution timed out after {self._timeout} seconds.",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="code_interpreter",
                content=f"Execution error: {exc}",
                success=False,
            )


__all__ = ["CodeInterpreterTool", "UnsafeCodeError"]
