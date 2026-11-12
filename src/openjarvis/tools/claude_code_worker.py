"""``delegate_to_claude_code`` - hand a coding / multi-step task to Claude Code.

Wraps the existing ``claude_code`` agent (Claude Agent SDK via a Node.js
runner). Claude Code can read, write and run things in the chosen folder, so
every delegation asks the user for approval first.

Requirements: Node.js >= 22 with npm on the machine, and ``ANTHROPIC_API_KEY``
in the server's environment. The runner's npm dependencies are installed on
first use (``~/.openjarvis/claude_code_runner``).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._approval_gate import (
    APPROVAL_WAIT_SECONDS,
    ApprovalOutcome,
    outcome_message,
    request_approval,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec

_TASK_TIMEOUT = 600
_MAX_RESULT_CHARS = 6000


def _ensure_node_on_path() -> bool:
    """Make Node.js findable even when the server started before it was installed."""
    if shutil.which("node"):
        return True
    candidates = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                candidates.append(Path(base) / "nodejs")
    else:
        candidates += [Path("/usr/local/bin"), Path("/opt/homebrew/bin")]
    for folder in candidates:
        if (folder / ("node.exe" if sys.platform.startswith("win") else "node")).exists():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            return True
    return False


def claude_code_ready() -> tuple[bool, str]:
    """(ready, reason) for showing status in the UI."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY is not set"
    if not _ensure_node_on_path():
        return False, "Node.js is not installed"
    return True, "ready"


@ToolRegistry.register("delegate_to_claude_code")
class DelegateToClaudeCodeTool(BaseTool):
    """Run a task with Claude Code in a chosen folder, after approval."""

    tool_id = "delegate_to_claude_code"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="delegate_to_claude_code",
            description=(
                "Hand a coding or multi-step computer task to Claude Code, an "
                "autonomous coding agent that can read, edit and create files "
                "and run commands inside one folder. Use for things like "
                "'write a script that...', 'fix the bug in my project', "
                "'organise these files'. Give a complete task description. "
                "The user must approve before it starts; it may take minutes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Complete instructions for Claude Code.",
                    },
                    "folder": {
                        "type": "string",
                        "description": "Folder Claude Code works in (default: ~/JarvisWorkspace).",
                    },
                },
                "required": ["task"],
            },
            category="pc",
            timeout_seconds=APPROVAL_WAIT_SECONDS + _TASK_TIMEOUT + 30,
        )

    def execute(self, **params: Any) -> ToolResult:
        task = str(params.get("task", "")).strip()
        if not task:
            return ToolResult(tool_name=self.tool_id, content="No task given.", success=False)
        ready, reason = claude_code_ready()
        if not ready:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Claude Code is not available: {reason}.",
                success=False,
            )
        folder = Path(str(params.get("folder") or Path.home() / "JarvisWorkspace")).expanduser()
        folder.mkdir(parents=True, exist_ok=True)

        summary = task if len(task) <= 160 else task[:157] + "..."
        outcome = request_approval(
            "delegate_to_claude_code",
            f"Let Claude Code work in {folder}: {summary}",
            {"task": task, "folder": str(folder)},
        )
        if outcome != ApprovalOutcome.APPROVED:
            return ToolResult(
                tool_name=self.tool_id,
                content=outcome_message(outcome, "the Claude Code task"),
                success=False,
            )

        try:
            from openjarvis.agents.claude_code import ClaudeCodeAgent

            agent = ClaudeCodeAgent(
                None,  # inference is handled by the Claude Agent SDK
                "",
                workspace=str(folder),
                timeout=_TASK_TIMEOUT,
                agent_id="jarvis_claude_code",
            )
            result = agent.run(task)
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Claude Code failed to run: {exc}",
                success=False,
            )
        content = (getattr(result, "content", "") or "").strip() or "(Claude Code returned no summary)"
        if len(content) > _MAX_RESULT_CHARS:
            content = content[:_MAX_RESULT_CHARS] + "\n... [truncated]"
        return ToolResult(
            tool_name=self.tool_id,
            content=f"Claude Code finished in {folder}:\n{content}",
            success=True,
        )


__all__ = ["DelegateToClaudeCodeTool", "claude_code_ready"]
