"""Voice context and recall shared by the Voice paths."""

from __future__ import annotations

import os
from typing import Any

GEMINI_LIVE_PREFIX_PADDING_MS_ENV = "OPENJARVIS_GEMINI_LIVE_PREFIX_PADDING_MS"
GEMINI_LIVE_SILENCE_DURATION_MS_ENV = "OPENJARVIS_GEMINI_LIVE_SILENCE_DURATION_MS"
VOICE_AUDIO_AHEAD_MS_ENV = "OPENJARVIS_VOICE_AUDIO_AHEAD_MS"
# How far ahead of the speaker the server may run. The browser holds a
# ~0.4s prebuffer to absorb the renderer's jitter, so a 500ms ceiling left it
# no room — the server blocked before the buffer could fill. Barge-in is
# unaffected: the browser stops every scheduled frame on interrupt.
DEFAULT_VOICE_AUDIO_AHEAD_MS = 2000
VOICE_MIN_SPEECH_CHUNK_CHARS_ENV = "OPENJARVIS_VOICE_MIN_SPEECH_CHUNK_CHARS"
# Measured on VieNeu: first audio arrives ~0.4s into a render call whatever
# the text length, while a short call renders slower than realtime (a 25-char
# sentence took 2.57s to make 1.76s of audio). Small chunks therefore buy no
# latency and starve playback between them. ~120 chars is roughly the point
# where a call renders faster than it plays.
DEFAULT_VOICE_MIN_SPEECH_CHUNK_CHARS = 120


def _vad_duration_ms(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value >= 0 else default


def _positive_duration_ms(name: str, default: int) -> int:
    value = _vad_duration_ms(name, default)
    return value if value > 0 else default


# The answer is going to a speaker, not a screen. Without this the agent
# writes chat markdown — bullet lists, **bold**, emoji — which is unreadable
# aloud and forces the renderer into many short calls it cannot keep up with.
VOICE_SYSTEM_PROMPT = (
    "You are answering out loud in a live voice conversation. "
    "Reply the way a person speaks: plain sentences, no markdown, no bullet "
    "lists, no headings, no emoji, no code blocks, no URLs read out. "
    "Keep it to two or three sentences unless the user asks for detail, and "
    "put the answer first. If you must list things, say them in a sentence "
    "separated by commas. Reply in the language the user spoke."
)


def _memory_recall(
    memory_backend: Any | None, config: Any | None
) -> tuple[Any | None, Any | None]:
    """Resolve the recall backend and its config, or (None, None) if disabled.

    Mirrors the chat path's gate: `config.agent.context_from_memory` off means
    no recall, exactly as in `/v1/chat/completions`.
    """
    if memory_backend is None or config is None:
        return None, None
    if not getattr(getattr(config, "agent", None), "context_from_memory", False):
        return None, None
    from openjarvis.tools.storage.context import ContextConfig

    memory = config.memory
    return memory_backend, ContextConfig(
        top_k=memory.context_top_k,
        min_score=memory.context_min_score,
        max_context_tokens=memory.context_max_tokens,
    )


__all__ = ["VOICE_SYSTEM_PROMPT", "_memory_recall"]
