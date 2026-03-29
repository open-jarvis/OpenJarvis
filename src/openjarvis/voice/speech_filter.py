"""Speech response filter — strips robotic filler, trims for TTS delivery.

Before any response goes to TTS, run it through ``prepare_for_speech()``.
This removes walls of text, filler openers, and markdown artifacts that sound
awful when read aloud.
"""

from __future__ import annotations

import re
from typing import Optional

# Phrases that sound stiff/robotic when spoken
_BANNED_OPENERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^here are[\s,]+", re.I), ""),
    (re.compile(r"^according to[\s,]+", re.I), ""),
    (re.compile(r"^in summary[\s,]*", re.I), ""),
    (re.compile(r"^in conclusion[\s,]*", re.I), ""),
    (re.compile(r"^certainly[!,.]?\s*", re.I), ""),
    (re.compile(r"^of course[!,.]?\s*", re.I), ""),
    (re.compile(r"^absolutely[!,.]?\s*", re.I), ""),
    (re.compile(r"^great question[!,.]?\s*", re.I), ""),
    (re.compile(r"^sure[!,.]?\s*", re.I), ""),
    (re.compile(r"^i'?d be happy to[\s,]+", re.I), ""),
    (re.compile(r"^as an ai[,.]?\s*", re.I), ""),
    (re.compile(r"^as your (ai |personal )?assistant[,.]?\s*", re.I), ""),
    (re.compile(r"^let me (know|explain|break|walk)[\s\w]*[.,]\s*", re.I), ""),
]

# Markdown that doesn't play well as speech
_MARKDOWN_CLEAN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),          # bold
    (re.compile(r"\*(.+?)\*"), r"\1"),               # italic
    (re.compile(r"`{1,3}(.+?)`{1,3}", re.S), r"\1"),  # code
    (re.compile(r"#{1,6}\s+"), ""),                   # headings
    (re.compile(r"^[\-*]\s+", re.M), ""),             # bullet points
    (re.compile(r"\[([^\]]+)\]\([^\)]+\)"), r"\1"),   # links → text only
    (re.compile(r"<[^>]+>"), ""),                      # HTML tags
]

# Max sentences to speak (unless user asked for more detail)
_DEFAULT_SENTENCE_LIMIT = 3


def _strip_markdown(text: str) -> str:
    for pattern, repl in _MARKDOWN_CLEAN:
        text = pattern.sub(repl, text)
    return text


def _strip_openers(text: str) -> str:
    for pattern, repl in _BANNED_OPENERS:
        text = pattern.sub(repl, text, count=1)
    return text.lstrip()


def _split_sentences(text: str) -> list[str]:
    # Naive sentence splitter; good enough for TTS trimming
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip()]


def prepare_for_speech(
    text: str,
    *,
    max_sentences: int = _DEFAULT_SENTENCE_LIMIT,
    full_response: bool = False,
) -> str:
    """Clean and trim a model response for spoken delivery.

    Parameters
    ----------
    text:
        Raw LLM response.
    max_sentences:
        Number of sentences to keep (ignored when ``full_response`` is True).
    full_response:
        Set True when the user explicitly asked for detail — skip trimming.
    """
    if not text:
        return text

    text = _strip_markdown(text)
    text = _strip_openers(text)

    # Collapse extra whitespace / blank lines
    text = re.sub(r"\n{2,}", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()

    if not full_response:
        sentences = _split_sentences(text)
        text = " ".join(sentences[:max_sentences])

    return text.strip()


def is_detail_request(text: str) -> bool:
    """Heuristic: did the user ask for more detail / full answer?"""
    patterns = [
        r"\bmore detail\b", r"\bfull (answer|response|explanation)\b",
        r"\btell me more\b", r"\bexpand\b", r"\belaborate\b",
        r"\bexplain\b", r"\bwalk me through\b", r"\bbreak.?down\b",
    ]
    return any(re.search(p, text, re.I) for p in patterns)


__all__ = ["is_detail_request", "prepare_for_speech"]
