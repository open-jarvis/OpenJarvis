"""PC action tools: let Jarvis operate the user's computer on request.

Low-risk, read-only or browser-only actions run directly:

* ``open_url``      - open an http(s) link in the default browser
* ``system_status`` - CPU, memory, disk, battery and time

Opening apps, files and folders runs immediately but is recorded in the approval
history; running commands asks the user first (see ``_approval_gate``):

* ``open_app``        - launch an application
* ``open_path``       - open a file or folder with its default program
* ``run_pc_command``  - run a PowerShell / shell command and return its output
"""

from __future__ import annotations

import datetime as _dt
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._approval_gate import (
    APPROVAL_WAIT_SECONDS,
    ApprovalOutcome,
    outcome_message,
    record_auto_action,
    request_approval,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec

_IS_WINDOWS = sys.platform.startswith("win")
_MAX_OUTPUT_CHARS = 4000
_COMMAND_TIMEOUT = 60

# Friendly names -> launch targets. Anything else is passed to the OS shell's
# "start"/"open" so installed apps and URI schemes (e.g. ms-settings:) work.
_WINDOWS_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "settings": "ms-settings:",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "spotify": "spotify:",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "camera": "microsoft.windows.camera:",
    "clock": "ms-clock:",
    "store": "ms-windows-store:",
}


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return (
        text[:_MAX_OUTPUT_CHARS]
        + f"\n... [{len(text) - _MAX_OUTPUT_CHARS} more characters]"
    )


def _os_open(target: str) -> None:
    """Open *target* (file, folder, URL, app name, URI) with the OS handler."""
    if _IS_WINDOWS:
        # ``start`` resolves App Paths (chrome, winword) and URI schemes that
        # os.startfile cannot. The empty "" is start's window-title argument.
        subprocess.Popen(  # noqa: S603
            ["cmd", "/c", "start", "", target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", target])  # noqa: S603,S607


def _fail(tool: str, message: str) -> ToolResult:
    return ToolResult(tool_name=tool, content=message, success=False)


def _ok(tool: str, message: str) -> ToolResult:
    return ToolResult(tool_name=tool, content=message, success=True)


# ---------------------------------------------------------------------------
# No approval needed
# ---------------------------------------------------------------------------


@ToolRegistry.register("open_url")
class OpenUrlTool(BaseTool):
    """Open a web page in the user's default browser."""

    tool_id = "open_url"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_url",
            description=(
                "Open a web page in the user's default browser on their PC. "
                "Use for requests like 'open YouTube' or 'show me the weather "
                "site'. Only http and https links."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full http(s) URL."},
                },
                "required": ["url"],
            },
            category="pc",
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        url = str(params.get("url", "")).strip()
        if url and "://" not in url:
            url = "https://" + url
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return _fail(
                "open_url", f"Refusing to open {url!r}: only http(s) links are allowed."
            )
        try:
            _os_open(url)
        except Exception as exc:
            return _fail("open_url", f"Could not open {url}: {exc}")
        return _ok("open_url", f"Opened {url} in the browser.")


@ToolRegistry.register("system_status")
class SystemStatusTool(BaseTool):
    """Report CPU, memory, disk, battery and the current time."""

    tool_id = "system_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="system_status",
            description=(
                "Read the PC's current status: date/time, CPU load, memory, "
                "main disk space, battery and uptime. Read-only."
            ),
            parameters={"type": "object", "properties": {}},
            category="pc",
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        lines = [f"Time: {_dt.datetime.now().strftime('%A %d %B %Y, %H:%M')}"]
        lines.append(f"System: {platform.system()} {platform.release()}")
        try:
            import psutil

            lines.append(
                f"CPU: {psutil.cpu_percent(interval=0.5):.0f}% used, "
                f"{psutil.cpu_count()} cores"
            )
            mem = psutil.virtual_memory()
            lines.append(
                f"Memory: {mem.percent:.0f}% used "
                f"({mem.used / 2**30:.1f} of {mem.total / 2**30:.1f} GB)"
            )
            root = Path.home().anchor or "/"
            disk = psutil.disk_usage(root)
            lines.append(
                f"Disk {root}: {disk.free / 2**30:.0f} GB free "
                f"of {disk.total / 2**30:.0f} GB"
            )
            battery = psutil.sensors_battery()
            if battery is not None:
                plug = "charging" if battery.power_plugged else "on battery"
                lines.append(f"Battery: {battery.percent:.0f}% ({plug})")
            boot = _dt.datetime.fromtimestamp(psutil.boot_time())
            hours = (_dt.datetime.now() - boot).total_seconds() / 3600
            lines.append(f"Uptime: {hours:.1f} hours")
        except Exception as exc:
            lines.append(f"(Detailed stats unavailable: {exc})")
        return _ok("system_status", "\n".join(lines))


# ---------------------------------------------------------------------------
# Approval required
# ---------------------------------------------------------------------------


@ToolRegistry.register("open_app")
class OpenAppTool(BaseTool):
    """Launch an application after the user approves."""

    tool_id = "open_app"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_app",
            description=(
                "Launch an application on the user's PC, e.g. 'notepad', "
                "'calculator', 'chrome', 'vs code', 'spotify', 'settings'. "
                "Runs immediately; each launch is logged."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app": {"type": "string", "description": "Application name."},
                },
                "required": ["app"],
            },
            category="pc",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        name = str(params.get("app", "")).strip()
        if not name:
            return _fail("open_app", "No application name given.")
        target = _WINDOWS_APPS.get(name.lower(), name) if _IS_WINDOWS else name
        try:
            _os_open(target)
        except Exception as exc:
            return _fail("open_app", f"Could not open {name}: {exc}")
        # Opening apps is a "safe" action: it runs without a card but is
        # still recorded in the approval history.
        record_auto_action("open_app", f"Open {name}", {"app": name, "launch": target})
        return _ok("open_app", f"Opened {name}.")


@ToolRegistry.register("open_path")
class OpenPathTool(BaseTool):
    """Open a file or folder with its default program after approval."""

    tool_id = "open_path"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_path",
            description=(
                "Open a file or folder on the user's PC with its default "
                "program (folders open in the file manager). Accepts '~' and "
                "names like 'Downloads', 'Documents', 'Desktop'. Runs "
                "immediately; each open is logged in the action history."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or folder path."},
                },
                "required": ["path"],
            },
            category="pc",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        raw = str(params.get("path", "")).strip().strip('"')
        if not raw:
            return _fail("open_path", "No path given.")
        known = {"downloads", "documents", "desktop", "pictures", "music", "videos"}
        path = (
            Path.home() / raw.capitalize()
            if raw.lower() in known
            else Path(raw).expanduser()
        )
        if not path.exists():
            return _fail("open_path", f"{path} does not exist.")
        try:
            _os_open(str(path))
        except Exception as exc:
            return _fail("open_path", f"Could not open {path}: {exc}")
        record_auto_action("open_path", f"Open {path}", {"path": str(path)})
        return _ok("open_path", f"Opened {path}.")


@ToolRegistry.register("run_pc_command")
class RunPcCommandTool(BaseTool):
    """Run a shell command after the user approves the exact command."""

    tool_id = "run_pc_command"

    @property
    def spec(self) -> ToolSpec:
        shell = "PowerShell" if _IS_WINDOWS else "the system shell"
        return ToolSpec(
            name="run_pc_command",
            description=(
                f"Run a command in {shell} on the user's PC and return its "
                "output. The user sees the exact command and must approve it. "
                "Prefer open_app / open_path / open_url for simply opening "
                "things. Times out after 60 seconds."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run."},
                    "working_dir": {
                        "type": "string",
                        "description": "Optional folder to run in (default: home).",
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "One short sentence shown to the user explaining why."
                        ),
                    },
                },
                "required": ["command"],
            },
            category="pc",
            timeout_seconds=APPROVAL_WAIT_SECONDS + _COMMAND_TIMEOUT + 15,
        )

    def execute(self, **params: Any) -> ToolResult:
        command = str(params.get("command", "")).strip()
        if not command:
            return _fail("run_pc_command", "No command given.")
        cwd = Path(str(params.get("working_dir") or Path.home())).expanduser()
        if not cwd.is_dir():
            return _fail("run_pc_command", f"Working folder {cwd} does not exist.")
        reason = str(params.get("reason") or "").strip()
        description = f"Run: {command}" + (f"  ({reason})" if reason else "")
        outcome = request_approval(
            "run_pc_command",
            description,
            {"command": command, "working_dir": str(cwd)},
        )
        if outcome != ApprovalOutcome.APPROVED:
            return _fail("run_pc_command", outcome_message(outcome, f"run `{command}`"))

        if _IS_WINDOWS:
            shell = shutil.which("powershell") or "powershell"
            argv = [shell, "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            argv = [os.environ.get("SHELL", "/bin/sh"), "-c", command]
        try:
            proc = subprocess.run(  # noqa: S603
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_COMMAND_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return _fail(
                "run_pc_command", f"`{command}` timed out after {_COMMAND_TIMEOUT}s."
            )
        except Exception as exc:
            return _fail("run_pc_command", f"Could not run `{command}`: {exc}")
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        body = out or "(no output)"
        if err:
            body += f"\n[stderr]\n{err}"
        return ToolResult(
            tool_name="run_pc_command",
            content=_truncate(f"Exit code {proc.returncode}\n{body}"),
            success=proc.returncode == 0,
        )


__all__ = [
    "OpenAppTool",
    "OpenPathTool",
    "OpenUrlTool",
    "RunPcCommandTool",
    "SystemStatusTool",
]
