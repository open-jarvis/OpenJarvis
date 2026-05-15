"""Container-scoped shell executor.

Runs commands inside the currently-active TB v2.1 task container (set via
:func:`openjarvis.tools.docker_shell_exec.set_active_container`). When no
container is active the tool refuses to run — it is explicitly not a
host-shell alternative.

The expected lifecycle is:

    from openjarvis.tools.docker_shell_exec import set_active_container

    set_active_container(container_name)
    try:
        # run agent — every shell command goes through `docker exec`
    finally:
        set_active_container(None)

The TB v2.1 task environment sets/clears this context automatically.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec

# NOTE: We use a module-level (process-wide) variable rather than a
# threading.local, because ToolExecutor dispatches each tool call onto a
# fresh ThreadPoolExecutor worker — thread-locals set on the runner
# thread are not visible there. The eval runner processes one task at
# a time per process, so there is no cross-task race. Parallelism
# across models is achieved through isolated HOMEs (separate processes).
_active_container: Optional[str] = None
_lock = threading.Lock()
_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 600


def set_active_container(name: Optional[str]) -> None:
    """Bind (or clear) the Docker container for this process."""
    global _active_container
    with _lock:
        _active_container = name


def get_active_container() -> Optional[str]:
    with _lock:
        return _active_container


@ToolRegistry.register("docker_shell_exec")
class DockerShellExecTool(BaseTool):
    """Execute a shell command inside the active TB v2.1 task container."""

    tool_id = "docker_shell_exec"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="docker_shell_exec",
            description=(
                "Execute a shell command inside the task's Linux container "
                "(the /app working directory is mounted and writable). Use "
                "this for ALL filesystem operations, running scripts, and "
                "installing packages. Returns stdout/stderr/exit-code."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "Shell command to execute. Runs through "
                            "`bash -c` inside the task container."
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": (
                            "Timeout in seconds (default 60, max 600)."
                        ),
                    },
                    "working_dir": {
                        "type": "string",
                        "description": (
                            "Container-side working directory (default /app)."
                        ),
                    },
                },
                "required": ["command"],
            },
            category="system",
            requires_confirmation=False,
            timeout_seconds=float(_MAX_TIMEOUT),
            required_capabilities=["code:execute"],
        )

    def execute(self, **params: Any) -> ToolResult:
        container = get_active_container()
        if not container:
            return ToolResult(
                tool_name="docker_shell_exec",
                content=(
                    "No active task container. This tool can only run "
                    "inside a TerminalBench V2.1 task environment."
                ),
                success=False,
            )

        command = params.get("command", "")
        if not command:
            return ToolResult(
                tool_name="docker_shell_exec",
                content="No command provided.",
                success=False,
            )

        try:
            timeout = int(params.get("timeout", _DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT
        timeout = max(1, min(timeout, _MAX_TIMEOUT))

        working_dir = params.get("working_dir") or "/app"

        cmd = [
            "docker",
            "exec",
            "-w",
            str(working_dir),
            container,
            "bash",
            "-c",
            command,
        ]
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name="docker_shell_exec",
                content=(
                    f"Command timed out after {timeout}s: {command!r}"
                ),
                success=False,
            )

        body = (
            f"[exit {r.returncode}]\n"
            + (f"--- stdout ---\n{r.stdout}\n" if r.stdout else "")
            + (f"--- stderr ---\n{r.stderr}\n" if r.stderr else "")
        )
        return ToolResult(
            tool_name="docker_shell_exec",
            content=body.strip() or f"[exit {r.returncode}]",
            success=(r.returncode == 0),
            metadata={
                "exit_code": r.returncode,
                "stdout": r.stdout,
                "stderr": r.stderr,
            },
        )


__all__ = [
    "DockerShellExecTool",
    "get_active_container",
    "set_active_container",
]
