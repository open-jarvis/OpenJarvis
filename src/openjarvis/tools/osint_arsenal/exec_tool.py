"""OSINT Arsenal Execution Tool for OpenJarvis Agents.

Executes OSINT tools from the arsenal index:
- Web tools → returns URL to open
- CLI tools → executes install_command or the tool itself via shell_exec
- Streams long-running output back if applicable
"""

from __future__ import annotations

import re
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.osint_arsenal.search_tool import _ensure_index

# Maximum output size per execution (100 KB)
_MAX_OUTPUT_BYTES = 102_400

# Default timeout for OSINT tool execution
_DEFAULT_TIMEOUT = 60


@ToolRegistry.register("osint_exec")
class OsintExecTool(BaseTool):
    """Execute an OSINT tool from the arsenal by name."""

    tool_id = "osint_exec"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="osint_exec",
            description=(
                "Execute an OSINT tool from the arsenal by name. "
                "Given a tool name and a target (domain, IP, username, email, etc.), "
                "runs the tool and returns the output. "
                "For web tools, returns the URL to open. "
                "For CLI tools, executes the command via shell_exec."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the OSINT tool to execute (must exist in the arsenal).",
                    },
                    "target": {
                        "type": "string",
                        "description": "Target to run the tool against (domain, IP, username, email, etc.).",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 60, max 300).",
                        "default": 60,
                    },
                },
                "required": ["tool_name", "target"],
            },
            category="osint",
            cost_estimate=0.0,
            latency_estimate=5.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        tool_name: str = params.get("tool_name", "")
        target: str = params.get("target", "")
        timeout: int = min(int(params.get("timeout", _DEFAULT_TIMEOUT)), 300)

        if not tool_name:
            return ToolResult(
                tool_name="osint_exec",
                content="Error: tool_name is required.",
                success=False,
            )
        if not target:
            return ToolResult(
                tool_name="osint_exec",
                content="Error: target is required.",
                success=False,
            )

        index = _ensure_index()
        if not index:
            return ToolResult(
                tool_name="osint_exec",
                content="Error: OSINT Arsenal index not found.",
                success=False,
            )

        # Find tool by name (case-insensitive)
        tool: dict[str, Any] | None = None
        for t in index:
            if t.get("name", "").lower() == tool_name.lower():
                tool = t
                break

        if not tool:
            return ToolResult(
                tool_name="osint_exec",
                content=f"Error: Tool '{tool_name}' not found in the arsenal.",
                success=False,
            )

        url = tool.get("url", "")
        install_command = tool.get("install_command", "")
        description = tool.get("description", "")
        category = tool.get("category", "")

        # Web tool → return URL with target substituted if applicable
        if url and not install_command:
            # Try to substitute {target} placeholder if present
            final_url = url.replace("{target}", target)
            return ToolResult(
                tool_name="osint_exec",
                content=f"Web tool ready: {tool_name}\nURL: {final_url}",
                success=True,
                metadata={
                    "type": "web",
                    "url": final_url,
                    "tool": tool_name,
                    "target": target,
                },
            )

        # CLI tool → build and execute command
        if install_command:
            # Build execution command: substitute {target} and common placeholders
            command = install_command.replace("{target}", target)
            command = command.replace("{domain}", target)
            command = command.replace("{ip}", target)
            command = command.replace("{username}", target)
            command = command.replace("{email}", target)

            # If command looks like just an install command (contains pip/go/apt/npm install)
            # we run it as-is, otherwise we assume it's the actual tool invocation
            is_install_only = bool(
                re.search(
                    r"\b(pip|npm|yarn|go|apt|brew|cargo|gem|composer)\s+install\b",
                    command,
                    re.IGNORECASE,
                )
            )

            if is_install_only:
                # Return install instructions — user should install then run
                return ToolResult(
                    tool_name="osint_exec",
                    content=(
                        f"Install-only command for {tool_name}:\n"
                        f"{command}\n\n"
                        f"After installation, run the tool manually against target: {target}"
                    ),
                    success=True,
                    metadata={
                        "type": "install",
                        "command": command,
                        "tool": tool_name,
                        "target": target,
                    },
                )

            # Execute via shell_exec
            try:
                from openjarvis.tools.shell_exec import ShellExecTool

                shell_tool = ShellExecTool()
                shell_result = shell_tool.execute(command=command, timeout=timeout)

                output = shell_result.content
                if len(output.encode("utf-8")) > _MAX_OUTPUT_BYTES:
                    output = output[:_MAX_OUTPUT_BYTES] + "\n... [truncated]"

                return ToolResult(
                    tool_name="osint_exec",
                    content=(
                        f"Executed {tool_name} against {target}:\n"
                        f"Command: {command}\n\n"
                        f"Output:\n{output}"
                    ),
                    success=shell_result.success,
                    metadata={
                        "type": "cli",
                        "command": command,
                        "tool": tool_name,
                        "target": target,
                        "exit_code": shell_result.metadata.get("exit_code") if shell_result.metadata else None,
                    },
                )
            except Exception as exc:
                return ToolResult(
                    tool_name="osint_exec",
                    content=f"Execution failed for {tool_name}: {exc}",
                    success=False,
                    metadata={"type": "cli", "tool": tool_name, "target": target},
                )

        # Fallback — no actionable command
        return ToolResult(
            tool_name="osint_exec",
            content=(
                f"Tool: {tool_name} ({category})\n"
                f"Description: {description}\n"
                f"No install command or URL available to execute automatically."
            ),
            success=True,
            metadata={"type": "info", "tool": tool_name, "target": target},
        )


__all__ = ["OsintExecTool"]
