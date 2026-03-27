"""Type-aware semantic chunker for Deep Research ingestion.

Splits text based on document type, never splitting mid-sentence.
Returns ``ChunkResult`` dataclass objects with section metadata and
inherited parent metadata.

Splitting strategy by doc_type
-------------------------------
- ``event``, ``contact`` : Always a single chunk; never split.
- ``email``              : Split on reply boundaries (``On … wrote:``),
                           then sentence-split within each part.
- ``message``            : Split on double-newline boundaries, accumulate
                           into chunks up to *max_tokens*.
- ``document``, ``note``,
  anything else          : Split on ``## Heading`` section boundaries →
                           paragraph boundaries (``\\n\\n``) within sections →
                           sentence boundaries as a last resort.

Token counting uses whitespace splitting: ``len(text.split())``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"])')
_SECTION_RE = re.compile(r"(?m)^##\s+(.+)$")
_REPLY_BOUNDARY_RE = re.compile(r"(?m)^On .+wrote:\s*$")


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
    """Split *text* into sentences using the canonical regex.

    The regex splits after sentence-ending punctuation (``.``, ``!``, ``?``)
    followed by whitespace and a capital letter or a double-quote.
    """
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _accumulate(
    segments: List[str],
    *,
    max_tokens: int,
    sep: str = " ",
) -> List[str]:
    """Greedily merge *segments* into chunks up to *max_tokens* tokens.

    A segment that is already larger than *max_tokens* is placed in its own
    chunk; it is never split further by this function.
    """
    chunks: List[str] = []
    current_parts: List[str] = []
    current_tokens = 0

    for seg in segments:
        seg_tokens = _count_tokens(seg)
        if current_parts and current_tokens + seg_tokens > max_tokens:
            chunks.append(sep.join(current_parts))
            current_parts = [seg]
            current_tokens = seg_tokens
        else:
            current_parts.append(seg)
            current_tokens += seg_tokens

    if current_parts:
        chunks.append(sep.join(current_parts))

    return chunks


def _sentence_chunks(text: str, *, max_tokens: int) -> List[str]:
    """Split *text* by sentences and accumulate into max_tokens chunks."""
    sentences = _split_sentences(text)
    if not sentences:
        stripped = text.strip()
        return [stripped] if stripped else []
    return _accumulate(sentences, max_tokens=max_tokens, sep=" ")


def _paragraph_chunks(text: str, *, max_tokens: int) -> List[str]:
    """Split *text* on paragraph breaks (``\\n\\n``), then by sentences if needed."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    result: List[str] = []
    for para in paragraphs:
        if _count_tokens(para) <= max_tokens:
            result.append(para)
        else:
            result.extend(_sentence_chunks(para, max_tokens=max_tokens))
    return result


# ---------------------------------------------------------------------------
# SemanticChunker
# ---------------------------------------------------------------------------


class SemanticChunker:
    """Split text based on document type without breaking mid-sentence.

    Parameters
    ----------
    max_tokens:
        Soft upper limit on chunk size measured in whitespace-delimited tokens
        (i.e. ``len(text.split())``).  Single unsplittable segments may exceed
        this limit.
    """

    def __init__(self, max_tokens: int = 512) -> None:
        self.max_tokens = max_tokens

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

        Parameters
        ----------
        text:      The raw text to split.
        doc_type:  Controls the splitting strategy (see module docstring).
        metadata:  Parent metadata dict; copied into every chunk's ``metadata``.

        Returns
        -------
        A list of ``ChunkResult`` objects with sequential 0-based ``index``
        values.  Returns an empty list if *text* is empty or whitespace-only.
        """
        if not text or not text.strip():
            return []

        parent_meta: Dict[str, Any] = dict(metadata or {})

        if doc_type in ("event", "contact"):
            raw_chunks = self._chunk_atomic(text)
        elif doc_type == "email":
            raw_chunks = self._chunk_email(text)
        elif doc_type == "message":
            raw_chunks = self._chunk_message(text)
        else:
            # "document", "note", or any unknown type
            raw_chunks = self._chunk_document(text)

        results: List[ChunkResult] = []
        for idx, (content, extra_meta) in enumerate(raw_chunks):
            merged: Dict[str, Any] = dict(parent_meta)
            merged.update(extra_meta)
            results.append(ChunkResult(content=content, index=idx, metadata=merged))

        return results

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _chunk_atomic(self, text: str) -> List[tuple[str, Dict[str, Any]]]:
        """Return the entire text as a single chunk (event / contact)."""
        return [(text, {})]

    def _chunk_email(self, text: str) -> List[tuple[str, Dict[str, Any]]]:
        """Split on reply boundaries; sentence-split each part."""
        # Split the email into parts on "On ... wrote:" lines.
        # re.split with a capturing group keeps the boundary in results,
        # so we re-attach the header to the following segment.
        boundaries = _REPLY_BOUNDARY_RE.split(text)

        # Each boundary match is a separator; reassemble so the "On … wrote:"
        # line stays with the content that follows it (the quoted block).
        raw_parts: List[str] = []
        if boundaries:
            # The first element is the text before the first boundary (the
            # main reply body).
            raw_parts.append(boundaries[0])
            # Subsequent elements alternate: matched boundary, then text after.
            # Because we used split() (not findall), the boundaries themselves
            # are not in the list — only the text segments between them.
            # So boundaries[1:] are the segments after each matched header.
            # We need to re-find the headers to reassemble.
            headers = _REPLY_BOUNDARY_RE.findall(text)
            for header, body in zip(headers, boundaries[1:]):
                # We found the header text via findall; reconstruct the part.
                part = (header.strip() + "\n" + body).strip()
                raw_parts.append(part)

        chunks: List[tuple[str, Dict[str, Any]]] = []
        for part in raw_parts:
            part = part.strip()
            if not part:
                continue
            if _count_tokens(part) <= self.max_tokens:
                chunks.append((part, {}))
            else:
                for sub in _sentence_chunks(part, max_tokens=self.max_tokens):
                    if sub:
                        chunks.append((sub, {}))

        return chunks if chunks else [(text.strip(), {})]

    def _chunk_message(self, text: str) -> List[tuple[str, Dict[str, Any]]]:
        """Split on double-newline boundaries and accumulate up to max_tokens."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        raw_chunks = _accumulate(paragraphs, max_tokens=self.max_tokens, sep="\n\n")
        return [(c, {}) for c in raw_chunks if c]

    def _chunk_document(self, text: str) -> List[tuple[str, Dict[str, Any]]]:
        """Split on ## headings → paragraphs → sentences."""
        # Find all ## heading positions
        section_matches = list(_SECTION_RE.finditer(text))

        if not section_matches:
            # No headings — fall back to paragraph/sentence splitting
            raw_chunks = _paragraph_chunks(text, max_tokens=self.max_tokens)
            return [(c, {}) for c in raw_chunks if c]

        # Build (title, body_text) pairs for each section
        sections: List[tuple[str, str]] = []
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

        # Check for preamble text before the first heading
        preamble = text[: section_matches[0].start()].strip()
        result: List[tuple[str, Dict[str, Any]]] = []

        if preamble:
            for c in _paragraph_chunks(preamble, max_tokens=self.max_tokens):
                if c:
                    result.append((c, {}))

        for title, body in sections:
            section_meta: Dict[str, Any] = {"section": title}
            if not body:
                # Empty section — emit a placeholder chunk with just the title
                result.append((title, section_meta))
                continue

            para_chunks = _paragraph_chunks(body, max_tokens=self.max_tokens)
            for c in para_chunks:
                if c:
                    result.append((c, dict(section_meta)))

        return result if result else [(text.strip(), {})]


__all__ = ["ChunkResult", "SemanticChunker"]
