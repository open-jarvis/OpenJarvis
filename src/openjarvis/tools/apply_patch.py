"""Apply-patch tool — apply unified diff patches to files."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Hunk / patch parsing helpers
# ---------------------------------------------------------------------------

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class _Hunk:
    """A single hunk from a unified diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[str] = field(default_factory=list)


def _parse_patch(patch_text: str) -> tuple[Optional[str], List[_Hunk], bool]:
    """Parse a unified diff string into a target path, list of hunks, and creation flag.

    Returns
    -------
    (path, hunks, is_creation)
        *path* is extracted from the ``+++ b/...`` header if present, or
        ``None`` if no header is found.  *hunks* is a list of ``_Hunk``
        objects.  *is_creation* indicates whether this patch creates a new file.

    Raises
    ------
    ValueError
        If the patch text contains no valid hunks or is malformed.
    """
    lines = patch_text.splitlines(keepends=True)
    target_path: Optional[str] = None
    hunks: List[_Hunk] = []
    current_hunk: Optional[_Hunk] = None
    is_dev_null_source = False

    for raw_line in lines:
        line = raw_line.rstrip("\n\r")

        # Check source path from --- header
        if line.startswith("--- "):
            source_part = line[4:].strip().split("\t")[0].strip()
            if source_part.startswith(("a/", "b/")):
                source_part = source_part[2:]
            if source_part in ("/dev/null", "dev/null"):
                is_dev_null_source = True
            continue

        # Detect target path from +++ header
        if line.startswith("+++ "):
            path_part = line[4:].strip().split("\t")[0].strip()
            # Strip leading b/ or a/ prefix (git-style)
            if path_part.startswith(("b/", "a/")):
                path_part = path_part[2:]
            # Ignore /dev/null (file deletion)
            if path_part not in ("/dev/null", "dev/null"):
                target_path = path_part
            continue

        # Hunk header
        m = _HUNK_HEADER_RE.match(line)
        if m:
            current_hunk = _Hunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2)) if m.group(2) is not None else 1,
                new_start=int(m.group(3)),
                new_count=int(m.group(4)) if m.group(4) is not None else 1,
            )
            hunks.append(current_hunk)
            continue

        # Hunk body lines: context, additions, removals
        if current_hunk is not None:
            if line.startswith((" ", "+", "-")):
                current_hunk.lines.append(line)
            elif line == "\\ No newline at end of file":
                # Informational — skip
                continue
            # Blank line inside a hunk counts as context (space-prefixed)
            # but some diffs omit the leading space for empty context lines.
            elif line == "":
                current_hunk.lines.append(" ")

    if not hunks:
        raise ValueError("No hunks found in patch")

    is_creation = is_dev_null_source or bool(hunks and hunks[0].old_start == 0)

    return target_path, hunks, is_creation


def _apply_hunks(original: str, hunks: List[_Hunk], eol: Optional[str] = None) -> str:
    """Apply parsed hunks to the original file content.

    Raises
    ------
    ValueError
        If a context or removal line does not match the original file.
    """
    if eol is None:
        eol = "\r\n" if "\r\n" in original else "\n"

    orig_lines = original.splitlines(keepends=True)
    # Normalise: ensure every line ends with newline for matching purposes
    # (we'll reconstruct exactly later)

    # We work in 1-indexed line numbers to match diff convention.
    # offset tracks cumulative shift from insertions/removals.
    offset = 0

    for hunk_idx, hunk in enumerate(hunks):
        # Position in orig_lines (0-indexed).
        # In unified diffs for new or empty files, old_start=0 represents
        # the beginning of the file (index 0). Non-empty files use 1-indexed numbers.
        pos = (0 if hunk.old_start == 0 else hunk.old_start - 1) + offset
        new_lines: List[str] = []
        check_pos = pos

        for diff_line in hunk.lines:
            tag = diff_line[0]
            content = diff_line[1:]

            if tag == " ":
                # Context line — must match original
                if check_pos >= len(orig_lines):
                    raise ValueError(
                        f"Hunk {hunk_idx + 1}: context line beyond end of file"
                        f" (line {check_pos + 1})"
                    )
                orig_content = orig_lines[check_pos].rstrip("\n\r")
                if orig_content != content:
                    raise ValueError(
                        f"Hunk {hunk_idx + 1}: context mismatch at"
                        f" line {check_pos + 1}:"
                        f" expected {content!r},"
                        f" got {orig_content!r}"
                    )
                new_lines.append(orig_lines[check_pos])
                check_pos += 1

            elif tag == "-":
                # Removal — verify the line matches before removing
                if check_pos >= len(orig_lines):
                    raise ValueError(
                        f"Hunk {hunk_idx + 1}: removal line beyond end of file"
                        f" (line {check_pos + 1})"
                    )
                orig_content = orig_lines[check_pos].rstrip("\n\r")
                if orig_content != content:
                    raise ValueError(
                        f"Hunk {hunk_idx + 1}: removal mismatch at"
                        f" line {check_pos + 1}:"
                        f" expected {content!r},"
                        f" got {orig_content!r}"
                    )
                check_pos += 1
                # Do NOT append — line is removed

            elif tag == "+":
                # Addition
                new_lines.append(content + eol)

        # Splice the new lines into orig_lines
        consumed = check_pos - pos
        orig_lines[pos : pos + consumed] = new_lines
        offset += len(new_lines) - consumed

    return "".join(orig_lines)


# ---------------------------------------------------------------------------
# ApplyPatchTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("apply_patch")
class ApplyPatchTool(BaseTool):
    """Apply a unified diff patch to a file."""

    tool_id = "apply_patch"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="apply_patch",
            description=(
                "Apply a unified diff patch to a file."
                " Supports standard unified diff format with"
                " context lines, additions, and removals."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": ("The unified diff patch text to apply."),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Target file path. If omitted, auto-detected"
                            " from the patch +++ header."
                        ),
                    },
                    "backup": {
                        "type": "boolean",
                        "description": (
                            "Create a .bak backup before applying (default: true)."
                        ),
                    },
                },
                "required": ["patch"],
            },
            category="filesystem",
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        patch_text = params.get("patch", "")
        if not patch_text:
            return ToolResult(
                tool_name="apply_patch",
                content="No patch provided.",
                success=False,
            )

        # Parse the patch
        try:
            header_path, hunks, is_creation = _parse_patch(patch_text)
        except ValueError as exc:
            return ToolResult(
                tool_name="apply_patch",
                content=f"Malformed patch: {exc}",
                success=False,
            )

        # Determine target path
        target = params.get("path") or header_path
        if not target:
            return ToolResult(
                tool_name="apply_patch",
                content=(
                    "No target path provided and could not"
                    " auto-detect from patch header."
                ),
                success=False,
            )

        path = Path(target)

        # Block sensitive files
        from openjarvis.security.file_policy import is_sensitive_file

        if is_sensitive_file(path):
            return ToolResult(
                tool_name="apply_patch",
                content=f"Access denied: {target} is a sensitive file.",
                success=False,
            )

        # Check file exists
        file_existed = path.exists()
        if not file_existed:
            if not is_creation:
                return ToolResult(
                    tool_name="apply_patch",
                    content=f"File not found: {target}",
                    success=False,
                )
            original = ""
        else:
            if not path.is_file():
                return ToolResult(
                    tool_name="apply_patch",
                    content=f"Not a file: {target}",
                    success=False,
                )

            # Read original content
            try:
                with open(path, "r", encoding="utf-8", newline="") as f:
                    original = f.read()
            except (OSError, UnicodeDecodeError) as exc:
                return ToolResult(
                    tool_name="apply_patch",
                    content=f"Cannot read file: {exc}",
                    success=False,
                )

        # Detect newline convention
        if original:
            eol = "\r\n" if "\r\n" in original else "\n"
        else:
            eol = "\r\n" if "\r\n" in patch_text else "\n"

        # Apply hunks
        try:
            patched = _apply_hunks(original, hunks, eol=eol)
        except ValueError as exc:
            return ToolResult(
                tool_name="apply_patch",
                content=f"Patch failed: {exc}",
                success=False,
            )

        # Backup (only if file existed previously)
        backup = params.get("backup", True)
        backup_path: Optional[str] = None
        if backup and file_existed:
            bak = Path(str(path) + ".bak")
            try:
                shutil.copy2(str(path), str(bak))
                backup_path = str(bak)
            except OSError as exc:
                return ToolResult(
                    tool_name="apply_patch",
                    content=f"Backup failed: {exc}",
                    success=False,
                )

        # Ensure parent directory exists for new file creation or nested path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ToolResult(
                tool_name="apply_patch",
                content=f"Cannot create directories: {exc}",
                success=False,
            )

        # Write patched content
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(patched)
        except OSError as exc:
            return ToolResult(
                tool_name="apply_patch",
                content=f"Write failed: {exc}",
                success=False,
            )

        metadata: dict[str, Any] = {
            "path": str(path.resolve()),
            "hunks_applied": len(hunks),
        }
        if backup_path:
            metadata["backup_path"] = backup_path

        return ToolResult(
            tool_name="apply_patch",
            content=f"Patch applied successfully ({len(hunks)} hunk(s)).",
            success=True,
            metadata=metadata,
        )


__all__ = ["ApplyPatchTool"]
