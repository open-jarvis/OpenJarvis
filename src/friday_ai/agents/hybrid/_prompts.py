"""Bench-specific answer-format instructions for hybrid paradigm agents.

Ported from ``hybrid-local-cloud-compute/benches/{gaia,swebench_verified}/``.

Adapters in the hybrid harness call ``benches.format_prompt(task)`` to build
the full user prompt — the paradigms here take the formatted prompt directly,
so callers (the experiment runner or eval driver) use these helpers to build
the prompt once and hand the string to the agent's ``run(input=...)``.
"""

from __future__ import annotations

from typing import Any, Dict

GAIA_INSTRUCTION = (
    "GAIA expects a single short, exact answer. Reason as needed, then commit to "
    "one best answer. Your reply MUST end with exactly one line of the form:\n"
    "FINAL ANSWER: <answer>\n"
    "Formatting rules for <answer>:\n"
    "  - If a number, write digits only (no commas, no units, no $ or %). "
    "e.g. `34689`, not `34,689 papers`.\n"
    "  - If a string, use as few words as possible, no articles, no abbreviations.\n"
    "  - If a list, comma-separate it and apply the rules above to each element.\n"
    "Nothing should follow the FINAL ANSWER line."
)

SWEBENCH_INSTRUCTION = (
    "You are fixing a real Python bug from SWE-bench Verified. Your reply MUST "
    "end with a unified diff patch that fixes the bug. The patch MUST:\n"
    "  - Start with a `diff --git a/<path> b/<path>` line (one per file changed).\n"
    "  - Include the standard `--- a/<path>` and `+++ b/<path>` lines below it.\n"
    "  - Use proper hunk headers `@@ -start,len +start,len @@`.\n"
    "  - Apply cleanly against the repository at the given base commit.\n"
    "Wrap the patch in a ```diff ... ``` code fence. Do not include any prose "
    "after the fence — only the closing ```."
)


def format_gaia(task: Dict[str, Any]) -> str:
    return f"{GAIA_INSTRUCTION}\n\nQuestion:\n{task.get('question', '')}"


def format_swebench(task: Dict[str, Any]) -> str:
    header = SWEBENCH_INSTRUCTION + "\n\n"
    if task.get("repo"):
        header += f"Repository: {task['repo']}\n"
    if task.get("base_commit"):
        header += f"Base commit: {task['base_commit']}\n"
    header += "\nGitHub issue:\n"
    return header + task.get("problem_statement", "")


def format_prompt(task: Dict[str, Any]) -> str:
    """Dispatch on task shape — same contract as ``benches.format_prompt``."""
    if task.get("question"):
        return format_gaia(task)
    if task.get("problem_statement"):
        return format_swebench(task)
    return ""


__all__ = [
    "GAIA_INSTRUCTION",
    "SWEBENCH_INSTRUCTION",
    "format_gaia",
    "format_prompt",
    "format_swebench",
]
