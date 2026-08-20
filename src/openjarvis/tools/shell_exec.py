"""Shell execution tool — run shell commands with security constraints."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, List

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Maximum output size per stream (100 KB)
_MAX_OUTPUT_BYTES = 102_400

# Maximum allowed timeout (seconds)
_MAX_TIMEOUT = 300

# Default timeout (seconds)
_DEFAULT_TIMEOUT = 30

# Environment variables always passed through
_BASE_ENV_KEYS = ("PATH", "HOME", "USER", "LANG", "TERM")


@ToolRegistry.register("shell_exec")
class ShellExecTool(BaseTool):
    """Execute shell commands with a sanitised environment."""

    tool_id = "shell_exec"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="shell_exec",
            description=(
                "Execute a shell command and return its stdout/stderr."
                " Runs with a minimal environment for security."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": ("Timeout in seconds (default 30, max 300)."),
                    },
                    "working_dir": {
                        "type": "string",
                        "description": (
                            "Working directory for the command."
                            " Must exist and be a directory."
                        ),
                    },
                    "env_passthrough": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Additional environment variable names"
                            " to pass through from the host."
                        ),
                    },
                },
                "required": ["command"],
            },
            category="system",
            requires_confirmation=True,
            timeout_seconds=60.0,
            required_capabilities=["code:execute"],
        )

    def execute(self, **params: Any) -> ToolResult:
        command = params.get("command", "")
        if not command:
            return ToolResult(
                tool_name="shell_exec",
                content="No command provided.",
                success=False,
            )

        # Resolve timeout (capped at _MAX_TIMEOUT)
        timeout = params.get("timeout", _DEFAULT_TIMEOUT)
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT
        if timeout < 1:
            timeout = 1
        if timeout > _MAX_TIMEOUT:
            timeout = _MAX_TIMEOUT

        # Validate working_dir
        working_dir = params.get("working_dir")
        if working_dir is not None:
            wd_path = Path(working_dir)
            if not wd_path.exists():
                return ToolResult(
                    tool_name="shell_exec",
                    content=f"Working directory does not exist: {working_dir}",
                    success=False,
                )
            if not wd_path.is_dir():
                return ToolResult(
                    tool_name="shell_exec",
                    content=f"Working directory is not a directory: {working_dir}",
                    success=False,
                )

        # Build sanitised environment
        env: dict[str, str] = {}
        for key in _BASE_ENV_KEYS:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val

        env_passthrough: List[str] = params.get("env_passthrough") or []
        for key in env_passthrough:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val

        try:
            from openjarvis._rust_bridge import get_rust_module

            _rust = get_rust_module()
            output = _rust.ShellExecTool().execute(command, working_dir)
            return ToolResult(
                tool_name="shell_exec",
                content=output or "(no output)",
                success=True,
                metadata={
                    "returncode": 0,
                    "timeout_used": timeout,
                    "working_dir": working_dir,
                },
            )
        except ImportError:
            pass  # Fall through to subprocess below
        except Exception as exc:
            return ToolResult(
                tool_name="shell_exec",
                content=str(exc),
                success=False,
                metadata={
                    "returncode": -1,
                    "timeout_used": timeout,
                    "working_dir": working_dir,
                },
            )
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name="shell_exec",
                content=f"Command timed out after {timeout} seconds.",
                success=False,
                metadata={
                    "returncode": -1,
                    "timeout_used": timeout,
                    "working_dir": working_dir,
                },
            )
        except PermissionError as exc:
            return ToolResult(
                tool_name="shell_exec",
                content=f"Permission denied: {exc}",
                success=False,
            )
        except OSError as exc:
            return ToolResult(
                tool_name="shell_exec",
                content=f"OS error: {exc}",
                success=False,
            )

        # Truncate output if needed
        stdout = result.stdout
        stderr = result.stderr
        if len(stdout) > _MAX_OUTPUT_BYTES:
            stdout = stdout[:_MAX_OUTPUT_BYTES] + "\n... (stdout truncated)"
        if len(stderr) > _MAX_OUTPUT_BYTES:
            stderr = stderr[:_MAX_OUTPUT_BYTES] + "\n... (stderr truncated)"

        # Format output
        sections: list[str] = []
        if stdout:
            sections.append(f"=== STDOUT ===\n{stdout}")
        if stderr:
            sections.append(f"=== STDERR ===\n{stderr}")
        content = "\n".join(sections) if sections else "(no output)"

        return ToolResult(
            tool_name="shell_exec",
            content=content,
            success=result.returncode == 0,
            metadata={
                "returncode": result.returncode,
                "timeout_used": timeout,
                "working_dir": working_dir,
            },
        )


__all__ = ["ShellExecTool"]
