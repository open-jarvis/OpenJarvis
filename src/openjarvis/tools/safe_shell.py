"""Structured, no-shell subprocess execution for Phase 5."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.manifest import ToolManifest, manifest_from_spec
from openjarvis.tools.safe_filesystem import FilesystemPolicyError, SecurePathPolicy

_OUTPUT_LIMIT = 102_400
_BASE_ENV = frozenset(
    {
        "LANG",
        "LC_ALL",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TZ",
        "WINDIR",
    }
)
_SECRET_NAME = re.compile(
    r"(?i)(api.?key|authorization|credential|password|secret|token)"
)
_CREDENTIAL_VALUE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9]{12,})"
)
_SHELL_HOSTS = frozenset(
    {
        "bash",
        "bash.exe",
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "sh",
        "sh.exe",
        "wscript.exe",
    }
)
_PACKAGE_MANAGERS = frozenset(
    {
        "choco",
        "choco.exe",
        "npm",
        "npm.cmd",
        "pip",
        "pip.exe",
        "winget",
        "winget.exe",
    }
)
_SYSTEM_EXECUTABLES = frozenset(
    {
        "bcdedit.exe",
        "diskpart.exe",
        "format.com",
        "net.exe",
        "netsh.exe",
        "reg.exe",
        "schtasks.exe",
        "sc.exe",
        "shutdown.exe",
    }
)


class ShellPolicyError(PermissionError):
    pass


def _resolved_executable(value: str) -> Path:
    candidate = Path(value)
    located = str(candidate) if candidate.is_absolute() else shutil.which(value)
    if not located:
        raise ShellPolicyError(f"executable not found: {value}")
    return Path(located).resolve(strict=True)


class StructuredCommandPolicy:
    """Trusted executable, cwd, environment, and command-category policy."""

    def __init__(
        self,
        *,
        allowed_executables: tuple[str | Path, ...],
        path_policy: SecurePathPolicy,
        allowed_environment: frozenset[str] = frozenset(),
        full_machine: bool = False,
    ) -> None:
        if not allowed_executables and not full_machine:
            raise ValueError("at least one executable must be allowed")
        self.allowed_executables = frozenset(
            os.path.normcase(str(_resolved_executable(str(value))))
            for value in allowed_executables
        )
        self.path_policy = path_policy
        self.allowed_environment = allowed_environment
        self.full_machine = full_machine

    def validate(
        self,
        executable: str,
        arguments: list[str],
        working_dir: str,
        environment: list[dict[str, str]],
    ) -> tuple[Path, Path, dict[str, str], tuple[str, ...]]:
        resolved = _resolved_executable(executable)
        normalised = os.path.normcase(str(resolved))
        if not self.full_machine and normalised not in self.allowed_executables:
            raise ShellPolicyError("executable is not allowlisted")
        name = resolved.name.casefold()
        if not self.full_machine and name in _SHELL_HOSTS:
            raise ShellPolicyError("shell hosts are not available through shell.exec")
        if not self.full_machine and name in _PACKAGE_MANAGERS:
            raise ShellPolicyError("software installation is disabled")
        if not self.full_machine and name in _SYSTEM_EXECUTABLES:
            raise ShellPolicyError("system administration command is disabled")
        if not self.full_machine:
            self._validate_git(name, arguments)

        cwd = self.path_policy.resolve(working_dir, must_exist=True)
        if not cwd.is_dir():
            raise ShellPolicyError("working_dir must be a directory")
        values: dict[str, str] = {}
        for entry in environment:
            key = entry["name"]
            value = entry["value"]
            if key not in self.allowed_environment:
                raise ShellPolicyError(f"environment variable is not allowed: {key}")
            if _SECRET_NAME.search(key):
                raise ShellPolicyError(
                    "secret-bearing environment variables are blocked"
                )
            values[key] = value
        command = (str(resolved), *(str(argument) for argument in arguments))
        return resolved, cwd, values, command

    @staticmethod
    def _validate_git(name: str, arguments: list[str]) -> None:
        if name not in {"git", "git.exe"} or not arguments:
            return
        operation = arguments[0].casefold()
        if operation in {"push", "clean"}:
            raise ShellPolicyError(f"git {operation} is blocked")
        if operation == "reset" and any(arg == "--hard" for arg in arguments[1:]):
            raise ShellPolicyError("git reset --hard is blocked")
        if any(
            arg.casefold() in {"--force", "--force-with-lease", "-f"}
            for arg in arguments
        ):
            if operation == "push":
                raise ShellPolicyError("force-push is blocked")


def _safe_environment(extra: dict[str, str]) -> dict[str, str]:
    environment = {
        key: value for key in _BASE_ENV if (value := os.environ.get(key)) is not None
    }
    environment.update(extra)
    return environment


def _redact(text: str, values: tuple[str, ...]) -> str:
    redacted = _CREDENTIAL_VALUE.sub("[REDACTED]", text)
    for value in values:
        if len(value) >= 4:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def _terminate_owned_tree(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return True
    if os.name == "nt":
        _terminate_windows_tree(process.pid)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            time.sleep(0.1)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    return process.poll() is not None


def _terminate_windows_tree(root_pid: int) -> None:
    """Terminate only *root_pid* and descendants using Win32 APIs."""

    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    parents: dict[int, list[int]] = {}
    if snapshot != invalid_handle:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents.setdefault(int(entry.th32ParentProcessID), []).append(
                int(entry.th32ProcessID)
            )
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        kernel32.CloseHandle(snapshot)

    ordered: list[int] = []

    def collect(pid: int) -> None:
        for child in parents.get(pid, []):
            collect(child)
        ordered.append(pid)

    collect(root_pid)
    for pid in ordered:
        handle = kernel32.OpenProcess(0x0001 | 0x00100000, False, pid)
        if not handle:
            continue
        try:
            kernel32.TerminateProcess(handle, 1)
            kernel32.WaitForSingleObject(handle, 5000)
        finally:
            kernel32.CloseHandle(handle)


@ToolRegistry.register("shell.exec")
class SafeShellTool(BaseTool):
    """Run one explicitly allowlisted executable without a command shell."""

    tool_id = "shell.exec"

    def __init__(self, policy: StructuredCommandPolicy) -> None:
        self.policy = policy
        self._process_lock = threading.RLock()
        self._active_processes: dict[int, subprocess.Popen[bytes]] = {}
        self._interrupted_processes: set[int] = set()

    def interrupt(self) -> int:
        """Terminate every command currently owned by this tool instance."""

        with self._process_lock:
            processes = tuple(self._active_processes.values())
            self._interrupted_processes.update(process.pid for process in processes)
        for process in processes:
            _terminate_owned_tree(process)
        return len(processes)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Run one allowlisted executable with structured arguments, no shell, "
                "bounded output, and process-tree timeout handling."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "executable": {"type": "string", "minLength": 1},
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 4096},
                        "maxItems": 128,
                    },
                    "working_dir": {"type": "string", "minLength": 1},
                    "timeout": {"type": "integer"},
                    "environment": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "minLength": 1},
                                "value": {"type": "string", "maxLength": 8192},
                            },
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                        "maxItems": 32,
                    },
                    "expected_exit_codes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 16,
                    },
                },
                "required": ["executable", "arguments", "working_dir"],
            },
            category="system",
            requires_confirmation=True,
            timeout_seconds=300,
            required_capabilities=["code:execute"],
        )

    @property
    def manifest(self) -> ToolManifest:
        return manifest_from_spec(self.tool_id, self.spec).model_copy(
            update={
                "allowed_roots": tuple(
                    str(root) for root in self.policy.path_policy.roots
                )
            }
        )

    def execute(self, **params: Any) -> ToolResult:
        timeout = min(max(int(params.get("timeout", 30)), 1), 300)
        try:
            _, cwd, extra_env, command = self.policy.validate(
                params["executable"],
                params["arguments"],
                params["working_dir"],
                params.get("environment", []),
            )
            expected = tuple(params.get("expected_exit_codes", [0]))
            creationflags = 0
            popen_extra: dict[str, Any] = {}
            if os.name == "nt":
                creationflags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                )
            else:
                popen_extra["start_new_session"] = True
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=_safe_environment(extra_env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=creationflags,
                **popen_extra,
            )
            with self._process_lock:
                self._active_processes[process.pid] = process
            try:
                try:
                    stdout_bytes, stderr_bytes = process.communicate(timeout=timeout)
                    timed_out = False
                    tree_terminated = False
                except subprocess.TimeoutExpired:
                    tree_terminated = _terminate_owned_tree(process)
                    stdout_bytes, stderr_bytes = process.communicate()
                    timed_out = True
            finally:
                with self._process_lock:
                    self._active_processes.pop(process.pid, None)
                    interrupted = process.pid in self._interrupted_processes
                    self._interrupted_processes.discard(process.pid)
            values = tuple(extra_env.values())
            stdout = _redact(
                stdout_bytes[:_OUTPUT_LIMIT].decode("utf-8", errors="replace"),
                values,
            )
            stderr = _redact(
                stderr_bytes[:_OUTPUT_LIMIT].decode("utf-8", errors="replace"),
                values,
            )
            success = (
                not timed_out and not interrupted and process.returncode in expected
            )
            content = (
                "\n".join(part for part in (stdout.rstrip(), stderr.rstrip()) if part)
                or "(no output)"
            )
            if timed_out:
                content = f"Command timed out after {timeout} seconds.\n{content}"
            elif interrupted:
                content = f"Command stopped by owner.\n{content}"
            return ToolResult(
                tool_name=self.tool_id,
                content=content,
                success=success,
                metadata={
                    "returncode": process.returncode,
                    "timeout_used": timeout,
                    "timed_out": timed_out,
                    "interrupted": interrupted,
                    "process_tree_terminated": tree_terminated,
                    "working_dir": str(cwd),
                    "executable": command[0],
                    "stdout_truncated": len(stdout_bytes) > _OUTPUT_LIMIT,
                    "stderr_truncated": len(stderr_bytes) > _OUTPUT_LIMIT,
                    "shell": False,
                },
            )
        except (
            FilesystemPolicyError,
            KeyError,
            OSError,
            ShellPolicyError,
            ValueError,
        ) as exc:
            return ToolResult(tool_name=self.tool_id, content=str(exc), success=False)


__all__ = [
    "SafeShellTool",
    "ShellPolicyError",
    "StructuredCommandPolicy",
]
