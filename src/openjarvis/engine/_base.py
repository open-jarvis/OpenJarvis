"""Shared engine utilities and re-exports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Dict, List

from openjarvis.core.types import Message
from openjarvis.engine._stubs import InferenceEngine


class EngineConnectionError(Exception):
    """Raised when an engine is unreachable."""


def messages_to_dicts(messages: Sequence[Message]) -> List[Dict[str, Any]]:
    """Convert ``Message`` objects to OpenAI-format dicts."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        d: Dict[str, Any] = {"role": m.role.value, "content": m.content}
        if m.name:
            d["name"] = m.name
        if m.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        out.append(d)
    return out


def estimate_prompt_tokens(messages: Sequence[Message]) -> int:
    """Estimate full prompt token count from message content.

    Ollama's ``prompt_eval_count`` may report only *newly evaluated*
    tokens when KV-cache hits occur, under-counting the system prompt
    and earlier conversation turns.  This helper provides a
    cache-agnostic estimate so that downstream cost / FLOPs / energy
    calculations reflect the true prompt size — matching what a cloud
    provider would charge.

    Uses ~4 characters per token (standard BPE average for English) plus
    a small per-message overhead for role markers and separators.
    """
    total_chars = sum(len(m.content) for m in messages)
    # ~4 tokens overhead per message for role markers / separators
    overhead = len(messages) * 4
    return max(1, total_chars // 4 + overhead)


__all__ = [
    "EngineConnectionError",
    "InferenceEngine",
    "estimate_prompt_tokens",
    "messages_to_dicts",
]
