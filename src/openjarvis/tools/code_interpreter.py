"""Code interpreter tool — safe Python code execution in subprocess."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Dangerous patterns to block
_BLOCKED_PATTERNS = [
    "os.system",
    "os.popen",
    "subprocess.",
    "shutil.rmtree",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "__import__",
    "eval(",
    "exec(",
    "compile(",
    "open(",
]


@ToolRegistry.register("code_interpreter")
class CodeInterpreterTool(BaseTool):
    """Execute Python code in an isolated subprocess."""

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
                " Code runs in an isolated subprocess."
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

        # Security check
        for pattern in _BLOCKED_PATTERNS:
            if pattern in code:
                return ToolResult(
                    tool_name="code_interpreter",
                    content=f"Blocked: code contains prohibited pattern '{pattern}'",
                    success=False,
                )

        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=self._timeout,
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


__all__ = ["CodeInterpreterTool"]
