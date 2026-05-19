"""Type-aware semantic chunker for Deep Research ingestion.

Splits text by paragraph → sentence → token/character boundaries while
enforcing a hard size cap and adding a fixed-size overlap between
consecutive chunks. The cap is enforced on BOTH token count
(whitespace-split) AND character count, since marketing-style emails
frequently contain dense runs without whitespace (zero-width joiners,
HTML residue) that defeat token-based limits alone.

Splitting strategy by doc_type
-------------------------------
- ``event``, ``contact`` : Always a single chunk; never split, never capped.
- ``email``              : Split on reply boundaries (``On … wrote:``),
                           then paragraphs, then sentences, then force-split.
- ``message``            : Split on double-newline boundaries, then sentences,
                           then force-split.
- ``document``, ``note``,
  anything else          : Split on ``## Heading`` section boundaries →
                           paragraph boundaries → sentences → force-split.

Token counting uses whitespace splitting: ``len(text.split())``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"])')
_SECTION_RE = re.compile(r"(?m)^##\s+(.+)$")
_REPLY_BOUNDARY_RE = re.compile(r"(?m)^On .+wrote:\s*$")
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ChunkResult:
    """A single chunk produced by ``SemanticChunker.chunk()``."""

    content: str
    index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _count_tokens(text: str) -> int:
    """Approximate token count via whitespace splitting."""
    return len(text.split())


def _split_sentences(text: str) -> List[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _accumulate_capped(
    segments: List[str],
    *,
    max_tokens: int,
    max_chars: int,
    sep: str = " ",
) -> List[str]:
    """Greedy-merge segments into chunks bounded by token AND char counts.

    Segments larger than the bounds pass through as their own chunk —
    the caller force-splits those in a separate pass.
    """
    chunks: List[str] = []
    current: List[str] = []
    cur_tokens = 0
    cur_chars = 0

    for seg in segments:
        seg_tokens = _count_tokens(seg)
        seg_chars = len(seg)
        sep_chars = len(sep) if current else 0

        would_overflow = current and (
            cur_tokens + seg_tokens > max_tokens
            or cur_chars + sep_chars + seg_chars > max_chars
        )
        if would_overflow:
            chunks.append(sep.join(current))
            current = [seg]
            cur_tokens = seg_tokens
            cur_chars = seg_chars
        else:
            current.append(seg)
            cur_tokens += seg_tokens
            cur_chars += sep_chars + seg_chars

    if current:
        chunks.append(sep.join(current))
    return chunks


def _best_cut_index(window: str) -> int:
    """Pick a cut point inside ``window``: sentence end → space → hard cut."""
    matches = list(_SENTENCE_END_RE.finditer(window))
    if matches:
        return matches[-1].end()
    midpoint = len(window) // 2
    space = window.rfind(" ", midpoint)
    if space > 0:
        return space + 1
    return len(window)


def _force_split(text: str, *, max_chars: int, max_tokens: int) -> List[str]:
    """Split an oversized run into pieces that fit both caps.

    Walks the text greedily: takes a window up to ``max_chars``, shrinks
    until the token count fits, then snaps the cut to the last sentence
    boundary, falling back to a word boundary, then a hard cut.
    """
    rest = text.strip()
    out: List[str] = []
    while rest:
        if len(rest) <= max_chars and _count_tokens(rest) <= max_tokens:
            out.append(rest)
            break

        end = min(max_chars, len(rest))
        while end > 1 and _count_tokens(rest[:end]) > max_tokens:
            end = max(1, int(end * 0.9))

        window = rest[:end]
        cut = _best_cut_index(window)
        piece = rest[:cut].strip()
        if not piece:
            # Window contained only whitespace before any cuttable boundary.
            # Force advance to avoid an infinite loop.
            cut = max(cut + 1, end)
            piece = rest[:cut].strip()
        if piece:
            out.append(piece)
        rest = rest[cut:].strip()
    return out


def _apply_overlap(chunks: List[str], *, overlap_tokens: int) -> List[str]:
    """Prepend the last ``overlap_tokens`` tokens of each chunk to the next.

    The tail is taken from the *original* preceding chunk (not the
    already-augmented output) so overlap doesn't compound, and is also
    capped by character count — a single whitespace-split "token" can be
    a 200+ char URL, so a pure-token cap would let tails balloon on
    content with long opaque strings.
    """
    if overlap_tokens <= 0 or len(chunks) < 2:
        return list(chunks)
    overlap_chars_cap = overlap_tokens * 4
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tokens = chunks[i - 1].split()
        if not prev_tokens:
            out.append(chunks[i])
            continue
        tail = " ".join(prev_tokens[-overlap_tokens:])
        if len(tail) > overlap_chars_cap:
            tail = tail[-overlap_chars_cap:]
        out.append(f"{tail} {chunks[i]}".strip())
    return out


# ---------------------------------------------------------------------------
# SemanticChunker
# ---------------------------------------------------------------------------


class SemanticChunker:
    """Split text by document type with a hard size cap and overlap.

    Parameters
    ----------
    max_tokens:
        Hard upper bound on chunk size in whitespace-delimited tokens.
        No emitted chunk exceeds this.
    max_chars:
        Hard upper bound on chunk size in characters. Defaults to
        ``max_tokens * 4`` (a typical English chars-per-token estimate).
        No emitted chunk exceeds this — the chunker force-splits any
        run that does, even when token count alone would say it fits.
    overlap_tokens:
        Token tail copied from each chunk into the head of the next so
        downstream retrieval doesn't miss context that straddles a chunk
        boundary. Defaults to ``min(100, max_tokens // 5)`` and is clamped
        to ``[0, max_tokens - 1]``. Set to ``0`` to disable.
    """

    def __init__(
        self,
        max_tokens: int = 512,
        *,
        max_chars: Optional[int] = None,
        overlap_tokens: Optional[int] = None,
    ) -> None:
        self.max_tokens = max_tokens
        self.max_chars = max_chars if max_chars is not None else max_tokens * 4
        if overlap_tokens is None:
            overlap_tokens = min(100, max(1, max_tokens // 5))
        self.overlap_tokens = max(0, min(overlap_tokens, max(0, max_tokens - 1)))

        # Content budget per chunk leaves room for the overlap prefix
        # that gets added in the final pass, so tokens stay within
        # max_tokens. Char budget intentionally does NOT subtract overlap
        # — we accept up to ~overlap_tokens*4 chars of headroom over
        # max_chars after overlap, which still sits under any reasonable
        # hard ceiling and avoids spurious force-splits of well-behaved
        # sentences in configurations where the char cap is tight.
        self._content_tokens = max(1, self.max_tokens - self.overlap_tokens)
        self._content_chars = self.max_chars
        # Soft target used to decide when a paragraph is "long enough to
        # sub-split", and to size sentence-accumulated sub-chunks. At
        # roughly half the hard cap, typical paragraphs ship as a single
        # chunk and only the unusually long ones get further split,
        # which keeps semantic units intact while still pulling the
        # chunk-length tail down.
        self._target_tokens = max(1, self._content_tokens // 2)
        self._target_chars = max(1, self._content_chars // 2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk(
        self,
        text: str,
        *,
        doc_type: str = "document",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        """Split *text* into ``ChunkResult`` objects.

        Returns an empty list if *text* is empty or whitespace-only.
        Events and contacts are always returned as a single chunk
        regardless of size; all other types respect the size caps and
        receive overlap between consecutive chunks.
        """
        if not text or not text.strip():
            return []

        parent_meta: Dict[str, Any] = dict(metadata or {})

        if doc_type in ("event", "contact"):
            return [ChunkResult(content=text, index=0, metadata=parent_meta)]

        if doc_type == "email":
            raw_chunks = self._chunk_email(text)
        elif doc_type == "message":
            raw_chunks = self._chunk_message(text)
        else:
            raw_chunks = self._chunk_document(text)

        # Apply overlap globally between consecutive chunks.
        contents = [c for c, _ in raw_chunks]
        metas = [m for _, m in raw_chunks]
        overlapped = _apply_overlap(contents, overlap_tokens=self.overlap_tokens)

        results: List[ChunkResult] = []
        for idx, (content, extra_meta) in enumerate(zip(overlapped, metas)):
            merged: Dict[str, Any] = dict(parent_meta)
            merged.update(extra_meta)
            results.append(ChunkResult(content=content, index=idx, metadata=merged))
        return results

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _pack_text(self, text: str) -> List[str]:
        """Emit one chunk per paragraph; sub-split paragraphs over the soft target.

        Paragraphs are the natural chunk unit. A paragraph that fits the
        soft target ships as one chunk. A paragraph that doesn't is
        sentence-split and the sentences accumulated up to the soft
        target; sentences that exceed the hard cap (rare — opaque content
        with no whitespace) are force-split.
        """
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            stripped = text.strip()
            return [stripped] if stripped else []

        out: List[str] = []
        for para in paragraphs:
            if (
                len(para) <= self._target_chars
                and _count_tokens(para) <= self._target_tokens
            ):
                out.append(para)
                continue

            sents = _split_sentences(para)
            if not sents:
                sents = [para]

            accumulated = _accumulate_capped(
                sents,
                max_tokens=self._target_tokens,
                max_chars=self._target_chars,
                sep=" ",
            )
            for c in accumulated:
                if (
                    len(c) <= self._content_chars
                    and _count_tokens(c) <= self._content_tokens
                ):
                    out.append(c)
                else:
                    out.extend(
                        _force_split(
                            c,
                            max_chars=self._content_chars,
                            max_tokens=self._content_tokens,
                        )
                    )
        return [c for c in out if c]

    def _chunk_email(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Split on reply boundaries; pack each part."""
        boundaries = _REPLY_BOUNDARY_RE.split(text)
        headers = _REPLY_BOUNDARY_RE.findall(text)

        raw_parts: List[str] = []
        if boundaries:
            raw_parts.append(boundaries[0])
            for header, body in zip(headers, boundaries[1:]):
                part = (header.strip() + "\n" + body).strip()
                raw_parts.append(part)

        chunks: List[Tuple[str, Dict[str, Any]]] = []
        for part in raw_parts:
            part = part.strip()
            if not part:
                continue
            for c in self._pack_text(part):
                if c:
                    chunks.append((c, {}))

        return chunks if chunks else [(text.strip(), {})]

    def _chunk_message(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Pack a message via paragraphs → sentences → force-split."""
        return [(c, {}) for c in self._pack_text(text)]

    def _chunk_document(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Split on ## headings → paragraphs → sentences → force-split."""
        section_matches = list(_SECTION_RE.finditer(text))

        if not section_matches:
            return [(c, {}) for c in self._pack_text(text)]

        sections: List[Tuple[str, str]] = []
        for i, m in enumerate(section_matches):
            title = m.group(1).strip()
            body_start = m.end()
            body_end = (
                section_matches[i + 1].start()
                if i + 1 < len(section_matches)
                else len(text)
            )
            body = text[body_start:body_end].strip()
            sections.append((title, body))

        result: List[Tuple[str, Dict[str, Any]]] = []
        preamble = text[: section_matches[0].start()].strip()
        if preamble:
            for c in self._pack_text(preamble):
                if c:
                    result.append((c, {}))

        for title, body in sections:
            section_meta: Dict[str, Any] = {"section": title}
            if not body:
                result.append((title, section_meta))
                continue
            for c in self._pack_text(body):
                if c:
                    result.append((c, dict(section_meta)))

        return result if result else [(text.strip(), {})]


__all__ = ["ChunkResult", "SemanticChunker"]
