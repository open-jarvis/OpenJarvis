"""Document chunking with configurable size and overlap.

Splits text into fixed-size chunks (measured in whitespace-split tokens)
with a configurable overlap.  Paragraph boundaries are respected when they
fall within the chunk window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class ChunkConfig:
    """Parameters controlling the chunking strategy."""

    chunk_size: int = 512
    chunk_overlap: int = 64
    min_chunk_size: int = 50


@dataclass(slots=True)
class Chunk:
    """A single chunk produced by the chunking pipeline."""

    content: str
    source: str = ""
    offset: int = 0
    index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


def _count_tokens(text: str) -> int:
    """Approximate token count via whitespace split."""
    return len(text.split())


def chunk_text(
    text: str,
    *,
    source: str = "",
    config: Optional[ChunkConfig] = None,
) -> List[Chunk]:
    """Split *text* into chunks respecting paragraph boundaries.

    Parameters
    ----------
    text:
        The full document text.
    source:
        Originating filename or identifier.
    config:
        Chunking parameters (uses defaults if ``None``).

    Returns
    -------
    List of :class:`Chunk` objects, in order.
    """
    if not text or not text.strip():
        return []

    cfg = config or ChunkConfig()

    # Split into paragraphs (double newline)
    paragraphs = [p for p in text.split("\n\n") if p.strip()]

    chunks: List[Chunk] = []
    current_tokens: List[str] = []
    current_offset = 0
    chunk_start_offset = 0
    force_final_chunk = False

    def emit_current(consumed_offset: int) -> None:
        """Emit the buffer and retain a bounded overlap for the next chunk."""
        nonlocal current_tokens, chunk_start_offset, force_final_chunk

        chunks.append(
            Chunk(
                content=" ".join(current_tokens),
                source=source,
                offset=chunk_start_offset,
                index=len(chunks),
            )
        )

        # Even a malformed overlap >= chunk_size must leave room for forward
        # progress and may never make the next chunk exceed the hard bound.
        keep = min(cfg.chunk_overlap, max(0, len(current_tokens) - 1))
        current_tokens = current_tokens[-keep:] if keep else []
        chunk_start_offset = consumed_offset - keep
        force_final_chunk = False

    for para in paragraphs:
        para_tokens = para.split()
        would_overflow = len(current_tokens) + len(para_tokens) > cfg.chunk_size

        # Preserve a paragraph boundary when the buffered paragraph is large
        # enough to stand alone.  A sub-floor lead-in instead stays attached
        # to the following text; dropping it was the original #754 bug.
        preserve_sequence = force_final_chunk
        if current_tokens and would_overflow:
            if len(current_tokens) >= cfg.min_chunk_size:
                emit_current(current_offset)
            else:
                preserve_sequence = True

        para_index = 0
        while para_index < len(para_tokens):
            capacity = cfg.chunk_size - len(current_tokens)
            remaining = len(para_tokens) - para_index

            if remaining <= capacity:
                current_tokens.extend(para_tokens[para_index:])
                para_index = len(para_tokens)
                force_final_chunk = preserve_sequence
                break

            take = capacity
            remainder = remaining - take
            overlap = min(cfg.chunk_overlap, max(0, cfg.chunk_size - 1))

            # With no (or a small) configured overlap, a full window can
            # strand a sub-floor tail.  Rebalance the two windows when both
            # can satisfy the minimum; otherwise the preservation flag below
            # keeps the unavoidable short tail rather than losing content.
            tail_size = overlap + remainder
            if preserve_sequence and tail_size < cfg.min_chunk_size:
                shift = cfg.min_chunk_size - tail_size
                if len(current_tokens) + take - shift >= cfg.min_chunk_size:
                    take -= shift

            current_tokens.extend(para_tokens[para_index : para_index + take])
            para_index += take
            emit_current(current_offset + para_index)
            force_final_chunk = preserve_sequence

        current_offset += len(para_tokens)

    # Flush remaining tokens.
    #
    # ``min_chunk_size`` exists to discard tiny *trailing* fragments once a
    # document has already produced at least one chunk. It must NOT silently
    # drop an entire short document: indexing a folder of short notes would
    # otherwise report success while storing nothing (#502 follow-up). So if no
    # chunk has been emitted yet, keep the remaining content regardless of the
    # floor.
    if current_tokens:
        chunk_content = " ".join(current_tokens)
        if (
            not chunks
            or force_final_chunk
            or _count_tokens(chunk_content) >= cfg.min_chunk_size
        ):
            chunks.append(
                Chunk(
                    content=chunk_content,
                    source=source,
                    offset=chunk_start_offset,
                    index=len(chunks),
                )
            )

    return chunks


__all__ = ["Chunk", "ChunkConfig", "chunk_text"]
