"""Prompt diff utilities for the plan phase.

Handles the PATCH_SYSTEM_PROMPT → REPLACE_SYSTEM_PROMPT downgrade logic.
When the teacher proposes a PATCH edit, the planner checks if the diff
would change more than 50% of lines. If so, it downgrades to a full
REPLACE so the user sees the complete new prompt in the review queue.

See spec §6.3.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from openjarvis.learning.distillation.models import Edit, EditOp

logger = logging.getLogger(__name__)

# Threshold: if more than this fraction of lines change, downgrade to REPLACE
_DOWNGRADE_THRESHOLD = 0.5


def changed_line_ratio(original: str, modified: str) -> float:
    """Compute the fraction of lines that differ between two strings.

    Uses a simple line-by-line comparison. Returns 0.0 if both are empty,
    1.0 if one is empty and the other is not.
    """
    orig_lines = original.splitlines()
    mod_lines = modified.splitlines()

    if not orig_lines and not mod_lines:
        return 0.0
    if not orig_lines or not mod_lines:
        return 1.0

    max_len = max(len(orig_lines), len(mod_lines))
    changed = 0
    for i in range(max_len):
        orig = orig_lines[i] if i < len(orig_lines) else None
        mod = mod_lines[i] if i < len(mod_lines) else None
        if orig != mod:
            changed += 1

    return changed / max_len


def apply_unified_diff(original: str, diff: str) -> Optional[str]:
    """Apply a unified diff to the original string.

    Returns the patched string, or None if the diff cannot be applied.
    This is a simplified implementation that handles basic unified diffs.
    """
    try:
        lines = original.splitlines(keepends=True)
        result_lines: list[str] = []
        diff_lines = diff.splitlines(keepends=True)

        # Skip header lines (--- and +++)
        i = 0
        while i < len(diff_lines) and not diff_lines[i].startswith("@@"):
            i += 1

        # No hunk headers found — not a valid unified diff
        if i >= len(diff_lines):
            return None

        # Parse hunks
        src_idx = 0
        while i < len(diff_lines):
            line = diff_lines[i]
            if line.startswith("@@"):
                # Parse hunk header: @@ -start,count +start,count @@
                match = re.match(r"@@ -(\d+)", line)
                if not match:
                    return None
                hunk_start = int(match.group(1)) - 1  # 0-indexed
                # Copy lines before this hunk
                while src_idx < hunk_start:
                    if src_idx < len(lines):
                        result_lines.append(lines[src_idx])
                    src_idx += 1
                i += 1
                continue

            if line.startswith("-"):
                # Remove line from original
                src_idx += 1
            elif line.startswith("+"):
                # Add line to result
                content = line[1:]
                if not content.endswith("\n"):
                    content += "\n"
                result_lines.append(content)
            elif line.startswith(" "):
                # Context line — copy from original
                if src_idx < len(lines):
                    result_lines.append(lines[src_idx])
                src_idx += 1
            i += 1

        # Copy remaining lines
        while src_idx < len(lines):
            result_lines.append(lines[src_idx])
            src_idx += 1

        return "".join(result_lines)
    except Exception:
        logger.warning("Failed to apply unified diff")
        return None


def maybe_downgrade_to_replace(
    edit: Edit,
    *,
    prompt_reader: Callable[[str], str],
) -> Edit:
    """Downgrade PATCH_SYSTEM_PROMPT to REPLACE if the diff is large.

    Parameters
    ----------
    edit :
        The edit to check.
    prompt_reader :
        A callable that takes a target string (e.g. "agents.simple.system_prompt")
        and returns the current prompt content.

    Returns the edit unchanged if it's not a PATCH op, or if the diff is
    small enough. Returns a new REPLACE edit if the diff changes > 50% of
    lines or if the diff cannot be applied.
    """
    if edit.op != EditOp.PATCH_SYSTEM_PROMPT:
        return edit

    diff_str = edit.payload.get("diff", "")
    original = prompt_reader(edit.target)
    patched = apply_unified_diff(original, diff_str)

    if patched is None:
        # Can't apply the diff — downgrade to REPLACE with a warning
        logger.warning(
            "Edit %s: diff could not be applied, downgrading to REPLACE",
            edit.id,
        )
        return edit.model_copy(
            update={
                "op": EditOp.REPLACE_SYSTEM_PROMPT,
                "payload": {"new_content": diff_str},
            }
        )

    ratio = changed_line_ratio(original, patched)
    if ratio > _DOWNGRADE_THRESHOLD:
        logger.info(
            "Edit %s: diff changes %.0f%% of lines (>%.0f%%), "
            "downgrading PATCH → REPLACE",
            edit.id,
            ratio * 100,
            _DOWNGRADE_THRESHOLD * 100,
        )
        return edit.model_copy(
            update={
                "op": EditOp.REPLACE_SYSTEM_PROMPT,
                "payload": {"new_content": patched},
            }
        )

    return edit
