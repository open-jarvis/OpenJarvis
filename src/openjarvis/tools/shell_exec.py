"""Shell execution tool — run shell commands with security constraints."""

from __future__ import annotations

import locale
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, List

import psutil

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Maximum output size per stream (100 KB)
_MAX_OUTPUT_BYTES = 102_400

# Maximum allowed timeout (seconds)
_MAX_TIMEOUT = 300

# Default timeout (seconds)
_DEFAULT_TIMEOUT = 30

# Environment variables always passed through on every platform.
_PORTABLE_ENV_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "TERM",
)

# Windows needs these to bootstrap ordinary child processes: missing
# SystemRoot breaks Winsock/DNS initialization, while missing LOCALAPPDATA
# can make the Store Python launcher provision a fresh interpreter in cwd.
# Keep them conditional so a POSIX host that happens to define similarly
# named variables does not expand the tool's minimal environment.
_WINDOWS_ENV_KEYS = (
    "SystemRoot",
    "SystemDrive",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
)
_BASE_ENV_KEYS = _PORTABLE_ENV_KEYS + (_WINDOWS_ENV_KEYS if os.name == "nt" else ())


def _stop_shell(proc: subprocess.Popen) -> None:
    """Stop the owned POSIX group or known Windows descendants, then reap."""
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            children = psutil.Process(proc.pid).children(recursive=True)
        except psutil.Error:
            children = []
        for child in reversed(children):
            try:
                child.kill()
            except psutil.Error:
                pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=2)


def _read_output(stream: BinaryIO, label: str) -> str:
    stream.seek(0)
    raw = stream.read(_MAX_OUTPUT_BYTES + 1)
    text = (
        raw[:_MAX_OUTPUT_BYTES]
        .decode(locale.getpreferredencoding(False), errors="replace")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    return text + (f"\n... ({label} truncated)" if len(raw) > _MAX_OUTPUT_BYTES else "")


def _run_shell(command: str, timeout: int, cwd: str | None, env: dict[str, str]):
    # Files avoid waiting indefinitely for inherited output pipes on Windows
    # and keep a large command response out of application memory.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        # Shell syntax is this confirmed tool's API, not a string built from
        # unrelated request data. Its capability/confirmation gates stay intact.
        proc = subprocess.Popen(
            command,
            # nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true  # noqa: E501
            shell=True,  # nosec B602 -- this tool explicitly runs confirmed shell commands
            stdout=stdout,
            stderr=stderr,
            cwd=cwd,
            env=env,
            start_new_session=os.name == "posix",
        )
        try:
            proc.wait(timeout=timeout)
        except BaseException:
            _stop_shell(proc)
            raise
        return subprocess.CompletedProcess(
            command,
            proc.returncode,
            _read_output(stdout, "stdout"),
            _read_output(stderr, "stderr"),
        )


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

        # No Rust fast path here on purpose: the Rust ShellExecTool takes no
        # timeout or env and hides the exit code, so it skipped all three of
        # the checks above (#1332). Bring it back once the binding has parity.
        try:
            result = _run_shell(command, timeout, working_dir, env)
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

        stdout = result.stdout
        stderr = result.stderr

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
