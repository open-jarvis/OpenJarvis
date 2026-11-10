"""Shell execution tool with native-only secure execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MAX_TIMEOUT = 300
_DEFAULT_TIMEOUT = 30


@ToolRegistry.register("shell_exec")
class ShellExecTool(BaseTool):
    """Execute shell commands only through the isolated native backend."""

    tool_id = "shell_exec"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="shell_exec",
            description=(
                "Execute a shell command through the native isolated backend."
                " The child receives a minimal environment."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command."},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30, max 300).",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory for the command.",
                    },
                },
                "required": ["command"],
            },
            category="system",
            requires_confirmation=True,
            timeout_seconds=float(_DEFAULT_TIMEOUT),
            required_capabilities=["code:execute"],
        )

    def execute(self, **params: Any) -> ToolResult:
        command = params.get("command", "")
        working_dir = params.get("working_dir")
        timeout = params.get("timeout", _DEFAULT_TIMEOUT)
        try:
            timeout = int(timeout)
        except (TypeError, ValueError, OverflowError):
            timeout = _DEFAULT_TIMEOUT
        timeout = min(max(timeout, 1), _MAX_TIMEOUT)

        metadata = {
            "returncode": -1,
            "timeout_used": timeout,
            "working_dir": working_dir,
            "timed_out": False,
            "output_limited": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

        if not command:
            return ToolResult(
                tool_name="shell_exec",
                content="No command provided.",
                success=False,
                metadata=metadata,
            )

        if working_dir is not None:
            wd_path = Path(working_dir)
            if not wd_path.exists():
                return ToolResult(
                    tool_name="shell_exec",
                    content=f"Working directory does not exist: {working_dir}",
                    success=False,
                    metadata=metadata,
                )
            if not wd_path.is_dir():
                return ToolResult(
                    tool_name="shell_exec",
                    content=f"Working directory is not a directory: {working_dir}",
                    success=False,
                    metadata=metadata,
                )

        try:
            from openjarvis._rust_bridge import get_rust_module

            output = (
                get_rust_module()
                .ShellExecTool()
                .execute(
                    command,
                    working_dir,
                    timeout,
                )
            )
        except ImportError:
            return ToolResult(
                tool_name="shell_exec",
                content=(
                    "Secure native shell execution is unavailable; "
                    "command was not executed."
                ),
                success=False,
                metadata=metadata,
            )
        except PermissionError as exc:
            return ToolResult(
                tool_name="shell_exec",
                content=f"Permission denied: {exc}",
                success=False,
                metadata=metadata,
            )
        except OSError as exc:
            return ToolResult(
                tool_name="shell_exec",
                content=f"OS error: {exc}",
                success=False,
                metadata=metadata,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="shell_exec",
                content=str(exc),
                success=False,
                metadata=metadata,
            )

        metadata.update(
            returncode=output.returncode,
            timed_out=output.timed_out,
            output_limited=getattr(
                output,
                "output_limited",
                False,
            ),
            stdout_truncated=output.stdout_truncated,
            stderr_truncated=output.stderr_truncated,
        )
        return ToolResult(
            tool_name="shell_exec",
            content=output.content or "(no output)",
            success=bool(
                output.success
                and not output.timed_out
                and not metadata["output_limited"]
                and output.returncode == 0
            ),
            metadata=metadata,
        )


__all__ = ["ShellExecTool"]
