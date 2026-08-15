"""Convert canonical assistant Markdown into plain text for speech renderers."""

from __future__ import annotations

import re

import emoji
from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark")
_WHITESPACE = re.compile(r"\s+")
_LINK_DESTINATION_FRAGMENT = re.compile(r"\]\([^)]*\)?")
_PRESENTATION_DELIMITERS = re.compile(r"[*_~`\[\]]+")
_FENCE_OPENING = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSING = re.compile(r"^ {0,3}(`+|~+)[ \t]*$")
_BLOCKQUOTE_PREFIX = re.compile(r"^ {0,3}>[ \t]?")
_LIST_PREFIX = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+")
_TERMINAL_PUNCTUATION = frozenset(".!?…")


def _project_speech_text(text: str) -> str:
    parts: list[str] = []
    open_blocks: list[str] = []
    for token in _MARKDOWN.parse(text):
        if token.nesting == 1:
            open_blocks.append(token.type)
            continue
        if token.nesting == -1:
            open_blocks.pop()
            continue
        if token.type != "inline":
            continue
        inline_parts: list[str] = []
        for child in token.children or ():
            if child.type in {"text", "code_inline"}:
                inline_parts.append(child.content)
            elif child.type in {"softbreak", "hardbreak"}:
                inline_parts.append(" ")
        spoken = emoji.replace_emoji("".join(inline_parts), replace="").strip()
        if not spoken:
            continue
        if {"heading_open", "list_item_open"}.intersection(open_blocks) and spoken[
            -1
        ] not in _TERMINAL_PUNCTUATION:
            spoken += "."
        parts.append(spoken)
    return _WHITESPACE.sub(" ", " ".join(parts)).strip()


def normalize_speech_text(text: str) -> str:
    """Remove presentation-only syntax while preserving spoken content."""
    projected = _project_speech_text(text)
    projected = _LINK_DESTINATION_FRAGMENT.sub("", projected)
    projected = _PRESENTATION_DELIMITERS.sub("", projected)
    return _WHITESPACE.sub(" ", projected).strip()


class SpeechTextProjector:
    """Project canonical streamed text without exposing incomplete Markdown."""

    def __init__(self) -> None:
        self._pending = ""
        self._emitted = ""

    def push(self, text: str) -> str | None:
        self._pending += text
        projected = _project_speech_text(self._pending)
        unresolved = _PRESENTATION_DELIMITERS.search(projected)
        stable = projected[: unresolved.start()].rstrip() if unresolved else projected
        if not stable.startswith(self._emitted):
            return None
        speech = stable[len(self._emitted) :].strip()
        self._emitted = stable
        if unresolved is None and not _has_unclosed_fenced_block(self._pending):
            self._pending = ""
            self._emitted = ""
        return speech or None

    def finish(self) -> str | None:
        projected = normalize_speech_text(self._pending)
        speech = (
            projected[len(self._emitted) :].strip()
            if projected.startswith(self._emitted)
            else None
        )
        self._pending = ""
        self._emitted = ""
        return speech or None


def _has_unclosed_fenced_block(text: str) -> bool:
    opening: tuple[str, int, tuple[tuple[str, int], ...]] | None = None
    for line in text.splitlines():
        if opening is not None:
            content = _strip_fence_containers(line, opening[2])
            closing = _FENCE_CLOSING.match(content) if content is not None else None
            if closing is not None:
                marker = closing.group(1)
                if marker[0] == opening[0] and len(marker) >= opening[1]:
                    opening = None
            continue
        content, containers = _strip_container_prefixes(line)
        match = _FENCE_OPENING.match(content)
        if match is None:
            continue
        marker, info = match.groups()
        if marker[0] == "`" and "`" in info:
            continue
        opening = (marker[0], len(marker), containers)
    return opening is not None


def _strip_container_prefixes(line: str) -> tuple[str, tuple[tuple[str, int], ...]]:
    containers: list[tuple[str, int]] = []
    while True:
        blockquote = _BLOCKQUOTE_PREFIX.match(line)
        if blockquote is not None:
            containers.append(("blockquote", 0))
            line = line[blockquote.end() :]
            continue
        list_item = _LIST_PREFIX.match(line)
        if list_item is not None:
            containers.append(("list", list_item.end()))
            line = line[list_item.end() :]
            continue
        return line, tuple(containers)


def _strip_fence_containers(
    line: str, containers: tuple[tuple[str, int], ...]
) -> str | None:
    for kind, indent in containers:
        if kind == "blockquote":
            blockquote = _BLOCKQUOTE_PREFIX.match(line)
            if blockquote is None:
                return None
            line = line[blockquote.end() :]
            continue
        if not line.startswith(" " * indent):
            return None
        line = line[indent:]
    return line


__all__ = ["SpeechTextProjector", "normalize_speech_text"]
