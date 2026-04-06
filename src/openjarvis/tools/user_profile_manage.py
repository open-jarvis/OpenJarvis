"""Manage persistent user profile (USER.md).

Enhanced with section-aware operations so agents can read and write
structured profile data (identity, contacts, projects, preferences).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("user_profile_manage")
class UserProfileManageTool(BaseTool):
    """Read and update the structured personal profile (USER.md).

    Supports both flat (legacy) and section-aware operations.

    Actions
    -------
    read
        Return the complete profile text.
    read_section
        Return entries from a specific section (Identity, Contacts, etc.).
    add
        Append a bullet entry to a section (defaults to Notes).
    set_field
        Set or update a key-value field in a section.
    update
        Replace old entry text with new text (full-text match).
    remove
        Remove the first entry whose text contains the given pattern.
    """

    def __init__(self, user_path: Path | str = "~/.openjarvis/USER.md") -> None:
        self._user_path = Path(user_path).expanduser()

    def _store(self):
        from openjarvis.profile.store import ProfileStore
        return ProfileStore(self._user_path)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="user_profile_manage",
            description=(
                "Read or update the user's personal profile. "
                "Supports reading sections (Identity, Contacts, Active Projects, "
                "Preferences, Notes), setting key-value fields, and adding/removing "
                "free-form entries."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "read",
                            "read_section",
                            "add",
                            "set_field",
                            "update",
                            "remove",
                        ],
                        "description": "Action to perform on the user profile.",
                    },
                    "section": {
                        "type": "string",
                        "description": (
                            "Profile section name: Identity | Contacts | "
                            "Active Projects | Preferences | Notes. "
                            "Required for read_section, set_field, add, remove."
                        ),
                    },
                    "field": {
                        "type": "string",
                        "description": (
                            "Field name for set_field action (e.g. 'Name', 'Timezone')."
                        ),
                    },
                    "entry": {
                        "type": "string",
                        "description": (
                            "Entry text to add, or pattern to match for remove/update."
                        ),
                    },
                    "new_entry": {
                        "type": "string",
                        "description": "Replacement text (for update action only).",
                    },
                },
                "required": ["action"],
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "read")
        section = params.get("section", "Notes")
        field = params.get("field", "")
        entry = params.get("entry", "")
        new_entry = params.get("new_entry", "")

        if action == "read":
            return self._read()
        if action == "read_section":
            return self._read_section(section)
        if action == "add":
            return self._add(section, entry)
        if action == "set_field":
            return self._set_field(section, field, entry)
        if action == "update":
            return self._update_legacy(entry, new_entry)
        if action == "remove":
            return self._remove(section, entry)

        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=f"Unknown action: {action}",
        )

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _read(self) -> ToolResult:
        store = self._store()
        text = store.render_full()
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=text or "(profile is empty)",
        )

    def _read_section(self, section: str) -> ToolResult:
        store = self._store()
        entries = store.get_section(section)
        if not entries:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content=f"(section '{section}' is empty or does not exist)",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="\n".join(entries),
        )

    def _add(self, section: str, entry: str) -> ToolResult:
        if not entry:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Entry text cannot be empty.",
            )
        store = self._store()
        store.ensure_template()
        store.add_item(section, entry)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Added to {section}: {entry}",
        )

    def _set_field(self, section: str, field: str, value: str) -> ToolResult:
        if not field:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Field name cannot be empty.",
            )
        store = self._store()
        store.ensure_template()
        store.set_field(section, field, value)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Set {section}.{field} = {value}",
        )

    def _update_legacy(self, old: str, new: str) -> ToolResult:
        """Legacy full-text replacement (kept for backward compatibility)."""
        if not self._user_path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Profile file does not exist.",
            )
        text = self._user_path.read_text(encoding="utf-8")
        if old not in text:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Text not found: {old}",
            )
        self._user_path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Updated entry.",
        )

    def _remove(self, section: str, pattern: str) -> ToolResult:
        if not pattern:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Pattern cannot be empty.",
            )
        store = self._store()
        removed = store.remove_item(section, pattern)
        if removed:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content=f"Removed entry matching '{pattern}' from {section}.",
            )
        # Legacy fallback: scan entire file
        if self._user_path.exists():
            text = self._user_path.read_text(encoding="utf-8")
            lines = text.split("\n")
            new_lines = [ln for ln in lines if pattern not in ln]
            if len(new_lines) < len(lines):
                self._user_path.write_text("\n".join(new_lines), encoding="utf-8")
                return ToolResult(
                    tool_name=self.spec.name,
                    success=True,
                    content=f"Removed entry matching '{pattern}'.",
                )
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=f"No entry found matching '{pattern}'.",
        )
