"""Read-only directory listing tool with optional path restrictions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._paths import resolve_allowed_dirs
from openjarvis.tools._stubs import BaseTool, ToolSpec

_DEFAULT_MAX_ENTRIES = 100
_MAX_ENTRIES = 500


@ToolRegistry.register("file_list")
class FileListTool(BaseTool):
    """List one directory without reading or changing its contents."""

    tool_id = "file_list"

    def __init__(self, allowed_dirs: Optional[List[str]] = None) -> None:
        self._allowed_dirs = [
            Path(directory).expanduser().resolve()
            for directory in resolve_allowed_dirs(allowed_dirs)
        ]

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_list",
            description="List files and subdirectories in a directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the directory to list.",
                    },
                    "max_entries": {
                        "type": "integer",
                        "description": (
                            "Maximum entries to return (default: 100, max: 500)."
                        ),
                    },
                },
                "required": ["path"],
            },
            category="filesystem",
        )

    def _is_path_allowed(self, path: Path) -> bool:
        if not self._allowed_dirs:
            return True
        return any(
            path == directory or path.is_relative_to(directory)
            for directory in self._allowed_dirs
        )

    def execute(self, **params: Any) -> ToolResult:
        file_path = params.get("path", "")
        if not isinstance(file_path, str) or not file_path:
            return ToolResult(
                tool_name=self.tool_id,
                content="No path provided.",
                success=False,
            )

        max_entries = params.get("max_entries", _DEFAULT_MAX_ENTRIES)
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            return ToolResult(
                tool_name=self.tool_id,
                content="max_entries must be an integer.",
                success=False,
            )
        max_entries = min(max(max_entries, 1), _MAX_ENTRIES)

        path = Path(file_path).expanduser()
        if not path.is_absolute() and self._allowed_dirs:
            path = self._allowed_dirs[0] / path

        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Cannot resolve directory: {exc}",
                success=False,
            )
        if not self._is_path_allowed(resolved):
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Access denied: {file_path} is outside allowed directories.",
                success=False,
            )
        if not resolved.exists():
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Directory not found: {file_path}",
                success=False,
            )
        if not resolved.is_dir():
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Not a directory: {file_path}",
                success=False,
            )

        from openjarvis.security.file_policy import is_sensitive_file

        try:
            entries = sorted(
                (entry for entry in resolved.iterdir() if not is_sensitive_file(entry)),
                key=lambda entry: entry.name.casefold(),
            )
            total = len(entries)
            lines = []
            for entry in entries[:max_entries]:
                kind = (
                    "directory" if entry.is_dir() and not entry.is_symlink() else "file"
                )
                lines.append(f"[{kind}] {entry.name}")
        except OSError as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Cannot list directory: {exc}",
                success=False,
            )

        content = "\n".join(lines) if lines else "(empty)"
        if total > max_entries:
            content += f"\n... and {total - max_entries} more entries."

        return ToolResult(
            tool_name=self.tool_id,
            content=content,
            success=True,
            metadata={
                "path": str(resolved),
                "count": min(total, max_entries),
                "total": total,
                "truncated": total > max_entries,
            },
        )


__all__ = ["FileListTool"]
