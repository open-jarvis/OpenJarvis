"""File read tool — read file contents with path validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Maximum file size to read (1 MB)
_MAX_SIZE_BYTES = 1_048_576
# Cap directory listings so huge trees do not blow the context window
_MAX_DIR_ENTRIES = 1000


@ToolRegistry.register("file_read")
class FileReadTool(BaseTool):
    """Read file contents with optional directory restrictions."""

    tool_id = "file_read"

    def __init__(
        self,
        allowed_dirs: Optional[List[str]] = None,
    ) -> None:
        self._allowed_dirs = [Path(d).resolve() for d in (allowed_dirs or [])]

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_read",
            description=(
                "Read a text file, or list top-level names if path is a directory "
                "(non-recursive; no shell required)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to a file or directory.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": (
                            "Max lines to return for files (default: all)."
                        ),
                    },
                },
                "required": ["path"],
            },
            category="filesystem",
        )

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if path is within allowed directories."""
        if not self._allowed_dirs:
            return True
        resolved = path.resolve()
        return any(
            resolved == d or resolved.is_relative_to(d) for d in self._allowed_dirs
        )

    def _list_directory(self, path: Path, file_path: str) -> ToolResult:
        """List immediate children of *path* (non-recursive)."""
        from openjarvis.security.file_policy import is_sensitive_file

        try:
            children = sorted(path.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            return ToolResult(
                tool_name="file_read",
                content=f"Cannot list directory {file_path}: {exc}",
                success=False,
            )
        visible = [c for c in children if not is_sensitive_file(c)]
        truncated = visible[:_MAX_DIR_ENTRIES]
        lines = [
            f"{c.name}{'/' if c.is_dir() else ''}" for c in truncated
        ]
        extra = len(visible) - len(truncated)
        header = (
            f"Directory listing for {path.resolve()} "
            f"({len(truncated)} of {len(visible)} entries shown"
        )
        if extra:
            header += f"; {extra} more not shown (cap {_MAX_DIR_ENTRIES})"
        header += "):\n"
        body = "\n".join(lines) if lines else "(empty)"
        return ToolResult(
            tool_name="file_read",
            content=header + body,
            success=True,
            metadata={
                "path": str(path.resolve()),
                "is_directory": True,
                "entry_count": len(truncated),
            },
        )

    def execute(self, **params: Any) -> ToolResult:
        file_path = params.get("path", "")
        if not file_path:
            return ToolResult(
                tool_name="file_read",
                content="No path provided.",
                success=False,
            )
        path = Path(file_path)
        # Block sensitive files (secrets, credentials, keys)
        from openjarvis.security.file_policy import is_sensitive_file

        if is_sensitive_file(path):
            return ToolResult(
                tool_name="file_read",
                content=f"Access denied: {file_path} is a sensitive file.",
                success=False,
            )
        if not path.exists():
            return ToolResult(
                tool_name="file_read",
                content=f"File not found: {file_path}",
                success=False,
            )
        if not self._is_path_allowed(path):
            return ToolResult(
                tool_name="file_read",
                content=f"Access denied: {file_path} is outside allowed directories.",
                success=False,
            )
        if path.is_dir():
            return self._list_directory(path, file_path)
        if not path.is_file():
            return ToolResult(
                tool_name="file_read",
                content=f"Not a readable file: {file_path}",
                success=False,
            )
        # Check size
        try:
            size = path.stat().st_size
        except OSError as exc:
            return ToolResult(
                tool_name="file_read",
                content=f"Cannot stat file: {exc}",
                success=False,
            )
        if size > _MAX_SIZE_BYTES:
            return ToolResult(
                tool_name="file_read",
                content=f"File too large: {size} bytes (max {_MAX_SIZE_BYTES}).",
                success=False,
            )
        try:
            from openjarvis._rust_bridge import get_rust_module

            _rust = get_rust_module()
            text = _rust.FileReadTool().execute(str(path))
        except ImportError:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(
                tool_name="file_read",
                content=f"Read error: {exc}",
                success=False,
            )
        max_lines = params.get("max_lines")
        if max_lines is not None and max_lines > 0:
            lines = text.splitlines(keepends=True)
            text = "".join(lines[:max_lines])
        return ToolResult(
            tool_name="file_read",
            content=text,
            success=True,
            metadata={"path": str(path.resolve()), "size_bytes": size},
        )


__all__ = ["FileReadTool"]
