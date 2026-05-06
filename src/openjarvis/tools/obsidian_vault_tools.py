"""Model-callable tools for the Railway-hosted Obsidian vault.

Each :class:`BaseTool` subclass here is registered via
``@ToolRegistry.register("vault_*")`` and surfaced to models through
``ToolExecutor.get_openai_tools()``. The tools wrap a curated subset of
the vault's 23 MCP operations — read/search/write — but deliberately
exclude bulk/destructive operations (``bulk_move_files``,
``rename_tag_everywhere``, ``archive_old_notes``) which are too easy to
misuse from a chat session.

Sensitive write tools (``vault_write``, ``vault_delete``) carry
``requires_confirmation = True`` so :class:`ToolExecutor` gates them
behind the operator's confirmation callback when running interactively.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.integrations.obsidian_vault import (
    ObsidianVaultClient,
    VaultUnavailableError,
    get_default_client,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _result(name: str, payload: Any) -> ToolResult:
    return ToolResult(tool_name=name, content=_serialize(payload), success=True)


def _error(name: str, exc: Exception) -> ToolResult:
    return ToolResult(
        tool_name=name,
        content=f"Vault error: {exc}",
        success=False,
    )


# ---------------------------------------------------------------------------
# Base for shared client wiring
# ---------------------------------------------------------------------------


class _VaultToolBase(BaseTool):
    """Mixin providing the shared singleton client."""

    is_local: bool = False  # external network call

    def __init__(self, client: Optional[ObsidianVaultClient] = None) -> None:
        self._client = client or get_default_client()


# ---------------------------------------------------------------------------
# Read-side tools
# ---------------------------------------------------------------------------


@ToolRegistry.register("vault_search")
class VaultSearchTool(_VaultToolBase):
    tool_id = "vault_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_search",
            description=(
                "Full-text search across notes in the shared Obsidian vault. "
                "Returns matching paths and snippets. Case-insensitive."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (substring match).",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matches to return.",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        max_results = int(params.get("max_results", 20))
        try:
            return _result(self.spec.name, self._client.search_files(query, max_results))
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


@ToolRegistry.register("vault_search_with_filters")
class VaultSearchWithFiltersTool(_VaultToolBase):
    tool_id = "vault_search_with_filters"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_search_with_filters",
            description=(
                "Advanced vault search combining content regex, tag, "
                "path-prefix, and frontmatter key/value filters. Use when "
                "vault_search returns too many irrelevant matches."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content_query": {
                        "type": "string",
                        "description": "Regex pattern for note body content.",
                    },
                    "tag": {
                        "type": "string",
                        "description": (
                            "Match notes with this tag (frontmatter or "
                            "inline #hashtag)."
                        ),
                    },
                    "path_prefix": {
                        "type": "string",
                        "description": (
                            "Restrict search to a vault subfolder, "
                            "e.g. 'Memory/' or 'Architecture/'."
                        ),
                    },
                    "frontmatter_key": {
                        "type": "string",
                        "description": "YAML frontmatter key to filter on.",
                    },
                    "frontmatter_value": {
                        "type": "string",
                        "description": "Required value for frontmatter_key.",
                    },
                },
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _result(
                self.spec.name,
                self._client.search_with_filters(
                    content_query=params.get("content_query"),
                    tag=params.get("tag"),
                    path_prefix=params.get("path_prefix"),
                    frontmatter_key=params.get("frontmatter_key"),
                    frontmatter_value=params.get("frontmatter_value"),
                ),
            )
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


@ToolRegistry.register("vault_read")
class VaultReadTool(_VaultToolBase):
    tool_id = "vault_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_read",
            description="Read a vault note's full content by path.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Vault-relative path including extension, "
                            "e.g. 'Memory/2026-05-07/note-abc.md'."
                        ),
                    },
                },
                "required": ["path"],
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path", "")
        try:
            return _result(self.spec.name, self._client.read_file(path))
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


@ToolRegistry.register("vault_list_directory")
class VaultListDirectoryTool(_VaultToolBase):
    tool_id = "vault_list_directory"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_list_directory",
            description="List all .md notes under a vault folder (root if path omitted).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Folder path (empty = vault root).",
                    },
                },
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path", "")
        try:
            return _result(self.spec.name, self._client.list_directory(path))
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


@ToolRegistry.register("vault_recent_notes")
class VaultRecentNotesTool(_VaultToolBase):
    tool_id = "vault_recent_notes"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_recent_notes",
            description="List the most recently modified vault notes.",
            parameters={
                "type": "object",
                "properties": {
                    "n": {
                        "type": "integer",
                        "description": "Number of notes to return (max 100).",
                        "default": 10,
                    },
                },
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        n = min(int(params.get("n", 10)), 100)
        try:
            return _result(self.spec.name, self._client.get_recent_notes(n))
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


@ToolRegistry.register("vault_summary")
class VaultSummaryTool(_VaultToolBase):
    tool_id = "vault_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_summary",
            description=(
                "Vault digest grouped by folder with note counts and word "
                "counts — useful for orienting before deeper search."
            ),
            parameters={"type": "object", "properties": {}},
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _result(self.spec.name, self._client.get_vault_summary())
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


@ToolRegistry.register("vault_get_backlinks")
class VaultBacklinksTool(_VaultToolBase):
    tool_id = "vault_get_backlinks"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_get_backlinks",
            description=(
                "List notes that link to the given note (via [[wikilinks]] "
                "or markdown links). Useful for context expansion."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Target note path."},
                },
                "required": ["path"],
            },
            category="memory",
        )

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path", "")
        try:
            return _result(self.spec.name, self._client.get_backlinks(path))
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


# ---------------------------------------------------------------------------
# Write-side tools (gated by confirmation)
# ---------------------------------------------------------------------------


@ToolRegistry.register("vault_write")
class VaultWriteTool(_VaultToolBase):
    tool_id = "vault_write"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_write",
            description=(
                "Create or overwrite a vault note. Use this to persist "
                "decisions, architecture notes, or insights worth keeping."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Vault-relative path (must end in .md).",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Full markdown content including any YAML "
                            "frontmatter."
                        ),
                    },
                },
                "required": ["path", "content"],
            },
            category="memory",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _result(
                self.spec.name,
                self._client.write_file(params.get("path", ""), params.get("content", "")),
            )
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


@ToolRegistry.register("vault_append")
class VaultAppendTool(_VaultToolBase):
    tool_id = "vault_append"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vault_append",
            description=(
                "Append text to a vault note (creates it if missing). "
                "Use for incremental log entries; do not use for "
                "structured frontmatter updates."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            category="memory",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _result(
                self.spec.name,
                self._client.append_to_file(
                    params.get("path", ""), params.get("content", "")
                ),
            )
        except VaultUnavailableError as exc:
            return _error(self.spec.name, exc)


__all__ = [
    "VaultAppendTool",
    "VaultBacklinksTool",
    "VaultListDirectoryTool",
    "VaultReadTool",
    "VaultRecentNotesTool",
    "VaultSearchTool",
    "VaultSearchWithFiltersTool",
    "VaultSummaryTool",
    "VaultWriteTool",
]
