"""Shared engine utilities and re-exports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Dict, List

from openjarvis.core.types import Message
from openjarvis.engine._stubs import InferenceEngine


class EngineConnectionError(Exception):
    """Raised when an engine is unreachable."""


class EngineContextLengthError(EngineConnectionError):
    """The prompt exceeds the served model's maximum context window.

    Subclasses ``EngineConnectionError`` so existing ``except
    EngineConnectionError`` handlers keep catching it, while callers that want a
    distinct, user-facing "conversation too long" message can branch on this type
    (or the ``is_context_length_error`` marker) instead of surfacing a generic
    engine failure.
    """

    is_context_length_error: bool = True


# Substrings that identify an error body as a context-window overflow (vLLM,
# SGLang, and OpenAI-compatible servers phrase this a few different ways).
# Every marker is anchored on "context" on purpose: generic phrases like
# "please reduce" or "too many tokens" also appear in unrelated 400 bodies
# (max_tokens validation, rate limiting, oversized images) and would
# misclassify those as "conversation too long".
CONTEXT_LENGTH_MARKERS = (
    "context length",
    "maximum context",
    "context window",
    "maximum_context",
    "context_length_exceeded",
)


def looks_like_context_length_error(text: str) -> bool:
    """True when *text* reads like a context-window overflow error.

    The single shared heuristic for recognizing vendor context-overflow
    phrasings — used by the engine layer (typing upstream 400s), agent error
    classification, and the server stream bridge, so a new vendor phrasing
    only ever needs to be added here.
    """
    low = (text or "").lower()
    return any(marker in low for marker in CONTEXT_LENGTH_MARKERS)


_REASONING_METADATA_KEYS = ("reasoning_content", "thinking")


def _message_estimated_chars(message: Message) -> int:
    parts = [message.text]
    for key in _REASONING_METADATA_KEYS:
        value = message.metadata.get(key)
        if isinstance(value, str):
            parts.append(value)
    for tc in message.tool_calls or []:
        parts.extend((tc.id, tc.name, tc.arguments))
    if message.tool_call_id:
        parts.append(message.tool_call_id)
    return sum(len(part) for part in parts)


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
        # Vision: forward base64 images to the engine. Ollama's /api/chat
        # accepts an "images" array on a message; text messages skip this.
        if getattr(m, "images", None):
            d["images"] = list(m.images)
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
    a small per-message overhead for role markers and separators. Counts
    content, reasoning metadata, tool-call payloads, and tool result IDs
    because all are replayed into later prompt turns when present.
    """
    total_chars = sum(_message_estimated_chars(m) for m in messages)
    # ~4 tokens overhead per message for role markers / separators
    overhead = len(messages) * 4
    return max(1, total_chars // 4 + overhead)


__all__ = [
    "CONTEXT_LENGTH_MARKERS",
    "EngineConnectionError",
    "EngineContextLengthError",
    "InferenceEngine",
    "estimate_prompt_tokens",
    "looks_like_context_length_error",
    "messages_to_dicts",
]
