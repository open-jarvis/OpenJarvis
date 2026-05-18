"""Git tools — version control operations via subprocess."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

from openjarvis._rust_bridge import get_rust_module
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

# Maximum output size (50 KB)
_MAX_OUTPUT_BYTES = 50 * 1024


def _truncate(text: str) -> str:
    """Truncate output to _MAX_OUTPUT_BYTES."""
    if len(text.encode("utf-8", errors="replace")) > _MAX_OUTPUT_BYTES:
        text = text[:_MAX_OUTPUT_BYTES] + "\n... (output truncated)"
    return text


def _check_git() -> str | None:
    """Return an error message if git is not available, else None."""
    if shutil.which("git") is None:
        return "git binary not found on PATH."
    return None


def _run_git(
    args: list[str],
    cwd: str = ".",
) -> ToolResult:
    """Run a git command and return a ToolResult.

    Parameters
    ----------
    args:
        The full command list (e.g. ``["git", "status", "--porcelain"]``).
    cwd:
        Working directory for the command.

    Returns
    -------
    ToolResult
        With ``success`` derived from return code and ``metadata``
        containing ``returncode``.
    """
    tool_name = args[1] if len(args) > 1 else "git"
    tool_name = f"git_{tool_name}"

    err = _check_git()
    if err:
        return ToolResult(
            tool_name=tool_name,
            content=err,
            success=False,
        )

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
    except FileNotFoundError:
        return ToolResult(
            tool_name=tool_name,
            content="git binary not found.",
            success=False,
        )
    except NotADirectoryError as exc:
        return ToolResult(
            tool_name=tool_name,
            content=f"Invalid repository path: {exc}",
            success=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_name=tool_name,
            content="Command timed out after 30 seconds.",
            success=False,
        )

    output = result.stdout
    if result.stderr:
        output += ("\n" if output else "") + result.stderr
    output = _truncate(output)

    return ToolResult(
        tool_name=tool_name,
        content=output or "(no output)",
        success=result.returncode == 0,
        metadata={"returncode": result.returncode},
    )


# ---------------------------------------------------------------------------
# GitStatusTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("git_status")
class GitStatusTool(BaseTool):
    """Show the working tree status of a git repository."""

    tool_id = "git_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_status",
            description=(
                "Show the working tree status of a git repository."
                " Returns porcelain-format output."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": (
                            "Path to the git repository. Default: current directory."
                        ),
                    },
                },
                "required": [],
            },
            category="vcs",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        repo_path = params.get("repo_path", ".")
        _rust = get_rust_module()
        try:
            output = _rust.GitStatusTool().execute(repo_path)
            return ToolResult(
                tool_name="git_status",
                content=output or "(no output)",
                success=True,
                metadata={"returncode": 0},
            )
        except Exception as exc:
            return ToolResult(
                tool_name="git_status",
                content=f"Git status error: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# GitDiffTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("git_diff")
class GitDiffTool(BaseTool):
    """Show changes in the working tree or staging area."""

    tool_id = "git_diff"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_diff",
            description=(
                "Show changes in the working tree or staging area."
                " Use staged=true for staged changes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": (
                            "Path to the git repository. Default: current directory."
                        ),
                    },
                    "staged": {
                        "type": "boolean",
                        "description": (
                            "Show staged changes instead of unstaged. Default: false."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Specific file path to diff. Default: all files."
                        ),
                    },
                },
                "required": [],
            },
            category="vcs",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        repo_path = params.get("repo_path", ".")
        staged = params.get("staged", False)
        file_path = params.get("path")

        _rust = get_rust_module()
        if not staged and not file_path:
            try:
                output = _rust.GitDiffTool().execute(repo_path)
                return ToolResult(
                    tool_name="git_diff",
                    content=output or "(no output)",
                    success=True,
                    metadata={"returncode": 0},
                )
            except Exception as exc:
                return ToolResult(
                    tool_name="git_diff",
                    content=f"Git diff error: {exc}",
                    success=False,
                )

        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        if file_path:
            cmd.append("--")
            cmd.append(file_path)

        return _run_git(cmd, cwd=repo_path)


# ---------------------------------------------------------------------------
# GitCommitTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("git_commit")
class GitCommitTool(BaseTool):
    """Stage files and create a git commit."""

    tool_id = "git_commit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_commit",
            description=(
                "Stage files and create a git commit."
                " Optionally stage specific files before committing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Commit message.",
                    },
                    "repo_path": {
                        "type": "string",
                        "description": (
                            "Path to the git repository. Default: current directory."
                        ),
                    },
                    "files": {
                        "type": "string",
                        "description": (
                            "Comma-separated files to stage,"
                            ' or "." for all.'
                            " If omitted, commits already-staged files."
                        ),
                    },
                },
                "required": ["message"],
            },
            category="vcs",
            required_capabilities=["file:write"],
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        message = params.get("message", "")
        if not message:
            return ToolResult(
                tool_name="git_commit",
                content="No commit message provided.",
                success=False,
            )

        repo_path = params.get("repo_path", ".")
        files = params.get("files")

        # Stage files if specified
        if files:
            file_list = [f.strip() for f in files.split(",") if f.strip()]
            if not file_list:
                return ToolResult(
                    tool_name="git_commit",
                    content="Empty files list after parsing.",
                    success=False,
                )
            add_result = _run_git(
                ["git", "add"] + file_list,
                cwd=repo_path,
            )
            if not add_result.success:
                return ToolResult(
                    tool_name="git_commit",
                    content=f"git add failed: {add_result.content}",
                    success=False,
                    metadata=add_result.metadata,
                )

        # Commit
        return _run_git(
            ["git", "commit", "-m", message],
            cwd=repo_path,
        )


# ---------------------------------------------------------------------------
# GitLogTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("git_log")
class GitLogTool(BaseTool):
    """Show the commit history of a git repository."""

    tool_id = "git_log"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_log",
            description=(
                "Show recent commit history of a git repository."
                " Returns the last N commits."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": (
                            "Path to the git repository. Default: current directory."
                        ),
                    },
                    "count": {
                        "type": "integer",
                        "description": ("Number of commits to show. Default: 10."),
                    },
                    "oneline": {
                        "type": "boolean",
                        "description": ("Use --oneline format. Default: true."),
                    },
                },
                "required": [],
            },
            category="vcs",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        repo_path = params.get("repo_path", ".")
        count = params.get("count", 10)
        oneline = params.get("oneline", True)

        _rust = get_rust_module()
        try:
            output = _rust.GitLogTool().execute(repo_path, count)
            return ToolResult(
                tool_name="git_log",
                content=output or "(no output)",
                success=True,
                metadata={"returncode": 0},
            )
        except Exception as exc:
            logger.debug("Rust git_log fallback to CLI: %s", exc)

        cmd = ["git", "log", f"-{count}"]
        if oneline:
            cmd.append("--oneline")

        return _run_git(cmd, cwd=repo_path)


__all__ = ["GitStatusTool", "GitDiffTool", "GitCommitTool", "GitLogTool"]
