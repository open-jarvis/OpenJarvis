"""macOS automation tool for local personal-assistant workflows."""

from __future__ import annotations

import json
import platform
import subprocess
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _applescript_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@ToolRegistry.register("mac_automation")
class MacAutomationTool(BaseTool):
    """Perform common macOS desktop actions via native command-line tools."""

    tool_id = "mac_automation"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="mac_automation",
            description=(
                "Perform macOS desktop automation actions such as opening apps, "
                "opening URLs, revealing files in Finder, sending notifications, "
                "running Shortcuts, or running AppleScript."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "open_app",
                            "quit_app",
                            "open_url",
                            "reveal_file",
                            "notify",
                            "run_shortcut",
                            "run_applescript",
                        ],
                        "description": "macOS automation action to perform.",
                    },
                    "app_name": {
                        "type": "string",
                        "description": "Application name for open_app or quit_app.",
                    },
                    "url": {
                        "type": "string",
                        "description": "URL to open in the default browser.",
                    },
                    "path": {
                        "type": "string",
                        "description": "File path to reveal in Finder.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Notification message.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Notification title.",
                    },
                    "shortcut": {
                        "type": "string",
                        "description": "Apple Shortcut name to run.",
                    },
                    "script": {
                        "type": "string",
                        "description": "AppleScript source for run_applescript.",
                    },
                },
                "required": ["action"],
            },
            category="system",
            requires_confirmation=True,
            timeout_seconds=30.0,
            required_capabilities=["system:admin"],
        )

    def execute(self, **params: Any) -> ToolResult:
        if platform.system() != "Darwin":
            return ToolResult(
                tool_name="mac_automation",
                content="mac_automation is only available on macOS.",
                success=False,
            )

        action = str(params.get("action", "")).strip()
        if not action:
            return ToolResult(
                tool_name="mac_automation",
                content="No action provided.",
                success=False,
            )

        try:
            cmd = self._build_command(action, params)
        except ValueError as exc:
            return ToolResult(
                tool_name="mac_automation",
                content=str(exc),
                success=False,
            )

        result = _run(cmd)
        content = {
            "action": action,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
        return ToolResult(
            tool_name="mac_automation",
            content=json.dumps(content, ensure_ascii=False),
            success=result.returncode == 0,
            metadata={"returncode": result.returncode, "action": action},
        )

    def _build_command(self, action: str, params: dict[str, Any]) -> list[str]:
        if action == "open_app":
            app_name = str(params.get("app_name", "")).strip()
            if not app_name:
                raise ValueError("open_app requires app_name.")
            return ["open", "-a", app_name]

        if action == "quit_app":
            app_name = str(params.get("app_name", "")).strip()
            if not app_name:
                raise ValueError("quit_app requires app_name.")
            script = f'tell application "{app_name}" to quit'
            return ["osascript", "-e", script]

        if action == "open_url":
            url = str(params.get("url", "")).strip()
            if not url:
                raise ValueError("open_url requires url.")
            return ["open", url]

        if action == "reveal_file":
            path = str(params.get("path", "")).strip()
            if not path:
                raise ValueError("reveal_file requires path.")
            return ["open", "-R", path]

        if action == "notify":
            message = str(params.get("message", "")).strip()
            if not message:
                raise ValueError("notify requires message.")
            title = str(params.get("title", "OpenJarvis")).strip() or "OpenJarvis"
            script = (
                f"display notification {_applescript_string(message)} "
                f"with title {_applescript_string(title)}"
            )
            return ["osascript", "-e", script]

        if action == "run_shortcut":
            shortcut = str(params.get("shortcut", "")).strip()
            if not shortcut:
                raise ValueError("run_shortcut requires shortcut.")
            return ["shortcuts", "run", shortcut]

        if action == "run_applescript":
            script = str(params.get("script", "")).strip()
            if not script:
                raise ValueError("run_applescript requires script.")
            return ["osascript", "-e", script]

        raise ValueError(f"Unknown mac_automation action: {action}")


__all__ = ["MacAutomationTool"]
