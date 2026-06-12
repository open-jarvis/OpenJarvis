"""Filter silence and common Whisper hallucinations from STT output."""

from __future__ import annotations

import re

# Short phrases Whisper often emits on silence or very quiet audio.
_HALLUCINATION_PHRASES = frozenset(
    {
        "you",
        "thank you",
        "thanks",
        "thanks for watching",
        "thank you for watching",
        "bye",
        "goodbye",
        "see you",
        "see you next time",
        "subscribe",
        "music",
        "applause",
        "silence",
        "okay",
        "ok",
        "hmm",
        "um",
        "uh",
    }
)


def normalize_transcript(text: str) -> str:
    """Collapse whitespace and strip surrounding punctuation."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    return cleaned.strip(".,!?;:\"'-")


def is_likely_hallucination(text: str) -> bool:
    """True when text matches known silence/noise hallucinations."""
    normalized = normalize_transcript(text).lower()
    if not normalized:
        return True
    if normalized in _HALLUCINATION_PHRASES:
        return True
    # Single very short token under 4 chars (e.g. "you", "the")
    words = normalized.split()
    if len(words) == 1 and len(words[0]) <= 3:
        return True
    return False


def sanitize_transcription(text: str) -> str:
    """Return cleaned English text, or empty when likely hallucinated."""
    cleaned = normalize_transcript(text)
    if not cleaned:
        return ""
    if is_likely_hallucination(cleaned):
        return ""
    return cleaned
