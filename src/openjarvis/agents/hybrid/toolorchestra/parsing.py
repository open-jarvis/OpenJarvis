"""Action / tool-call parsing + prompt assembly for ToolOrchestraAgent."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# Regex for ``<tool_call>{...}</tool_call>`` blocks emitted by Orchestrator-8B
# when the vLLM tool parser doesn't catch them (e.g. `qwen3_xml` parser on a
# hermes-style template). Captures the JSON payload.
_TOOL_CALL_TAG_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

# Fallback for a known failure mode: the SFT'd orchestrator often emits its
# delegation as ``\boxed{expert_ab12: <sub-question>}`` (math-data habit bleeding
# into routing) instead of a real ``<tool_call>`` JSON block. The name before the
# colon is a valid (anonymized) tool label; the rest is the sub-question/args.
#
# Real outputs use several shapes, all handled here:
#   \boxed{web_search: <query>}              -> name, args
#   \boxed{web_search query: <query>}        -> the word "query" is dropped
#   \boxed{file_read, path: <path>}          -> the ", <key>" hint sets the arg key
# We require a ``name <optional , key | query> : <args>`` structure, so a genuine
# answer like ``\boxed{10}``, ``\boxed{b,e}`` or ``\boxed{The answer is: 42}``
# (first token isn't followed by a bare ``:`` / ``, key:`` / ``query:``) is left
# alone. ``group("key")`` is the explicit arg key when the model wrote ``, key:``.
_BOXED_DELEGATION_RE = re.compile(
    r"\\boxed\{\s*([A-Za-z_][\w-]*)\s*"
    r"(?:,\s*(?P<key>\w+)\s*)?"  # optional ", key" hint (e.g. file_read, path:)
    r"(?:query\s*)?"  # optional literal "query" word before the colon
    r":\s*(.+?)\s*\}\s*$",
    re.DOTALL,
)


def _parse_rl_tool_call(content: str, sdk_tool_calls: Any) -> Optional[Dict[str, Any]]:
    """Return ``{"name": str, "arguments": dict}`` or None.

    Prefers the SDK-level ``tool_calls`` (when vLLM's parser matched), falls
    back to scraping ``<tool_call>{...}</tool_call>`` tags from the raw
    content. We take the first tool call only — Orchestrator-8B was trained
    to emit exactly one per turn.
    """
    # SDK-level path.
    if sdk_tool_calls:
        first = sdk_tool_calls[0]
        name = getattr(getattr(first, "function", None), "name", None)
        args_raw = getattr(getattr(first, "function", None), "arguments", None) or "{}"
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError:
            args = {}
        if isinstance(name, str) and isinstance(args, dict):
            return {"name": name, "arguments": args}
    # Text-tag fallback.
    if not isinstance(content, str):
        return None
    m = _TOOL_CALL_TAG_RE.search(content)
    if m:
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            name = obj.get("name")
            args = obj.get("arguments", {})
            if isinstance(name, str) and isinstance(args, dict):
                return {"name": name, "arguments": args}
    # \boxed{name[, key][ query]: <args>} fallback (see _BOXED_DELEGATION_RE).
    bm = _BOXED_DELEGATION_RE.search(content.strip())
    if bm:
        arg_val = bm.groups()[-1].strip()
        key = bm.group("key") or "input"
        return {"name": bm.group(1), "arguments": {key: arg_val}}
    return None


def _build_pool_block(workers: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"Worker {w['id']} ({w['name']}): {w['description']}" for w in workers
    )


def _build_user_prompt(
    question: str,
    workers: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
) -> str:
    pieces = [
        f"Worker pool:\n{_build_pool_block(workers)}",
        f"User question:\n{question}",
    ]
    if history:
        pieces.append("Conversation so far (orchestrator turns and worker outputs):")
        for h in history:
            if h["role"] == "orchestrator":
                pieces.append(f"[Orchestrator turn {h['turn']}]\n{h['raw']}")
            else:
                pieces.append(
                    f"[Worker {h['worker_id']} ({h['worker_name']}) turn {h['turn']}]\n"
                    f"{h['output']}"
                )
    pieces.append(
        "Emit the next JSON action object now — exactly one object, no prose."
    )
    return "\n\n".join(pieces)


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    return s


def _parse_action(text: str) -> Optional[Dict[str, Any]]:
    s = _strip_fences(text)
    # First try direct parse, then balanced-brace extraction.
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "action" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start : i + 1])
                    if isinstance(obj, dict) and "action" in obj:
                        return obj
                except json.JSONDecodeError:
                    return None
    return None


def _extract_final_answer_text(text: str) -> str:
    """Best-effort: pull the answer string from a malformed action emission.

    Tries `"answer": "..."` regex, then the GAIA-style `FINAL ANSWER:` line.
    """
    m = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.DOTALL)
    if m:
        return m.group(1).encode("utf-8").decode("unicode_escape")
    m = re.search(r"FINAL\s*ANSWER\s*:\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1).strip()
    return text.strip()
