"""Text cleanup helpers for speech synthesis."""

from __future__ import annotations

import html
import re
from typing import List

_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BARE_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_BOLD_ITALIC_RE = re.compile(r"(\*\*|__|\*|_)([^*_]+)\1")
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_BREAK_RE = re.compile(r"\n{2,}")


def _format_german_time(match: re.Match[str]) -> str:
    hour = int(match.group(1))
    minute = match.group(2)
    if minute == "00":
        return f"{hour} Uhr"
    return f"{hour} Uhr {minute}"


def _split_long_sentence(sentence: str, max_chars: int) -> List[str]:
    sentence = sentence.strip()
    if len(sentence) <= max_chars:
        return [sentence]

    pieces = re.split(r"([,;:])\s+", sentence)
    chunks: List[str] = []
    current = ""

    for index in range(0, len(pieces), 2):
        clause = pieces[index].strip()
        separator = pieces[index + 1] if index + 1 < len(pieces) else ""
        if not clause:
            continue

        candidate = f"{current} {clause}".strip() if current else clause
        if len(candidate) > max_chars and current:
            chunks.append(_ensure_sentence_end(current))
            current = clause
        else:
            current = candidate

        if separator and len(current) < max_chars:
            current = f"{current}{separator}"

    if current:
        chunks.append(_ensure_sentence_end(current))
    return chunks or [sentence]


def _ensure_sentence_end(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] in ".!?":
        return text
    return f"{text}."


def _shorten_long_sentences(text: str, max_chars: int = 140) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text)
    shortened: List[str] = []
    for part in parts:
        shortened.extend(_split_long_sentence(part, max_chars=max_chars))
    return " ".join(p for p in shortened if p)


def normalize_for_tts(text: str) -> str:
    """Make assistant output easier for TTS engines to speak naturally."""
    if not text:
        return ""

    cleaned = html.unescape(text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _CODE_BLOCK_RE.sub(" Code ausgelassen. ", cleaned)
    cleaned = _INLINE_CODE_RE.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_LINK_RE.sub(r"\1", cleaned)
    cleaned = _BARE_URL_RE.sub("", cleaned)
    cleaned = _HEADING_RE.sub("", cleaned)
    cleaned = _BULLET_RE.sub("", cleaned)
    cleaned = cleaned.replace(">", "")
    cleaned = _BOLD_ITALIC_RE.sub(r"\2", cleaned)
    cleaned = cleaned.replace("|", ". ")
    cleaned = _TIME_RE.sub(_format_german_time, cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    cleaned = _MULTI_BREAK_RE.sub("\n", cleaned)
    cleaned = re.sub(r"\s*\n\s*", ". ", cleaned)
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    cleaned = _shorten_long_sentences(cleaned)
    return cleaned.strip()
