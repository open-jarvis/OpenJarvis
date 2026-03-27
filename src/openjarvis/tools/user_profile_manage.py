"""Manage persistent user profile (USER.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("user_profile_manage")
class UserProfileManageTool(BaseTool):
    """Manage persistent user profile (USER.md)."""

    def __init__(self, user_path: Path | str = "~/.openjarvis/USER.md") -> None:
        self._user_path = Path(user_path).expanduser()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="user_profile_manage",
            description=("Read, add, update, or remove entries in user profile."),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "add", "update", "remove"],
                        "description": "Action to perform on user profile.",
                    },
                    "entry": {
                        "type": "string",
                        "description": (
                            "The profile entry content (for add/update/remove)."
                        ),
                    },
                    "new_entry": {
                        "type": "string",
                        "description": (
                            "Replacement content (for update action only)."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "read")
        entry = params.get("entry", "")
        new_entry = params.get("new_entry", "")
        if action == "read":
            return self._read()
        elif action == "add":
            return self._add(entry)
        elif action == "update":
            return self._update(entry, new_entry)
        elif action == "remove":
            return self._remove(entry)
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=f"Unknown action: {action}",
        )

    def _read(self) -> ToolResult:
        content = ""
        if self._user_path.exists():
            content = self._user_path.read_text()
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=content or "(empty)",
        )

    def _add(self, entry: str) -> ToolResult:
        if not entry:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Entry cannot be empty.",
            )
        self._user_path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._user_path.read_text() if self._user_path.exists() else ""
        self._user_path.write_text(existing.rstrip() + f"\n- {entry}\n")
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Added: {entry}",
        )

    def _update(self, old: str, new: str) -> ToolResult:
        if not self._user_path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="User profile file does not exist.",
            )
        text = self._user_path.read_text()
        if old not in text:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Entry not found: {old}",
            )
        self._user_path.write_text(text.replace(old, new, 1))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Updated: {old} -> {new}",
        )

    def _remove(self, entry: str) -> ToolResult:
        if not self._user_path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="User profile file does not exist.",
            )
        text = self._user_path.read_text()
        lines = text.split("\n")
        new_lines = [ln for ln in lines if entry not in ln]
        if len(new_lines) == len(lines):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Entry not found: {entry}",
            )
        self._user_path.write_text("\n".join(new_lines))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Removed: {entry}",
        )
