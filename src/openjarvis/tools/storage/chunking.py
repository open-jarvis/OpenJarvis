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

    for para in paragraphs:
        para_tokens = para.split()

        # If adding this paragraph would exceed chunk_size and we already
        # have content, flush the current chunk first.
        if current_tokens and len(current_tokens) + len(para_tokens) > cfg.chunk_size:
            chunk_content = " ".join(current_tokens)
            if _count_tokens(chunk_content) >= cfg.min_chunk_size:
                chunks.append(
                    Chunk(
                        content=chunk_content,
                        source=source,
                        offset=chunk_start_offset,
                        index=len(chunks),
                    )
                )

            # Keep the overlap tail for the next chunk
            if cfg.chunk_overlap > 0 and len(current_tokens) > cfg.chunk_overlap:
                overlap = current_tokens[-cfg.chunk_overlap :]
                current_tokens = list(overlap)
            else:
                current_tokens = []
            chunk_start_offset = current_offset

        # If a single paragraph exceeds chunk_size, split it directly
        if len(para_tokens) > cfg.chunk_size:
            # Flush anything accumulated first
            if current_tokens:
                chunk_content = " ".join(current_tokens)
                if _count_tokens(chunk_content) >= cfg.min_chunk_size:
                    chunks.append(
                        Chunk(
                            content=chunk_content,
                            source=source,
                            offset=chunk_start_offset,
                            index=len(chunks),
                        )
                    )
                current_tokens = []

            # Split the oversized paragraph into fixed windows
            idx = 0
            while idx < len(para_tokens):
                window = para_tokens[idx : idx + cfg.chunk_size]
                chunk_content = " ".join(window)
                if _count_tokens(chunk_content) >= cfg.min_chunk_size:
                    chunks.append(
                        Chunk(
                            content=chunk_content,
                            source=source,
                            offset=current_offset + idx,
                            index=len(chunks),
                        )
                    )
                step = max(1, cfg.chunk_size - cfg.chunk_overlap)
                idx += step

            current_offset += len(para_tokens)
            chunk_start_offset = current_offset
            continue

        current_tokens.extend(para_tokens)
        current_offset += len(para_tokens)

    # Flush remaining tokens
    if current_tokens:
        chunk_content = " ".join(current_tokens)
        if _count_tokens(chunk_content) >= cfg.min_chunk_size:
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
