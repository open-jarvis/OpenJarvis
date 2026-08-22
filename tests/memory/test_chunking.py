"""Tests for the document chunking pipeline."""

from __future__ import annotations

import pytest

from openjarvis.tools.storage.chunking import ChunkConfig, chunk_text


def test_empty_string_returns_empty():
    assert chunk_text("") == []


def test_whitespace_only_returns_empty():
    assert chunk_text("   \n\n  ") == []


def test_short_text_single_chunk():
    # Need >= 50 words (default min_chunk_size)
    words = [f"word{i}" for i in range(60)]
    text = " ".join(words)
    chunks = chunk_text(text, source="test.txt")
    assert len(chunks) == 1
    assert chunks[0].source == "test.txt"
    assert chunks[0].index == 0
    assert "word0" in chunks[0].content


def test_long_text_multiple_chunks():
    # Build text that exceeds 512 tokens
    words = [f"word{i}" for i in range(600)]
    text = " ".join(words)
    chunks = chunk_text(text)
    assert len(chunks) >= 2


def test_chunk_overlap():
    cfg = ChunkConfig(chunk_size=100, chunk_overlap=20, min_chunk_size=5)
    words = [f"w{i}" for i in range(250)]
    text = " ".join(words)
    chunks = chunk_text(text, config=cfg)
    assert len(chunks) >= 2

    # The end of chunk 0 and start of chunk 1 should overlap
    first_tokens = chunks[0].content.split()
    second_tokens = chunks[1].content.split()
    tail = first_tokens[-20:]
    head = second_tokens[:20]
    assert tail == head


def test_paragraph_boundary_respected():
    cfg = ChunkConfig(chunk_size=20, chunk_overlap=0, min_chunk_size=3)
    para1 = " ".join(f"a{i}" for i in range(10))
    para2 = " ".join(f"b{i}" for i in range(10))
    text = f"{para1}\n\n{para2}"
    chunks = chunk_text(text, config=cfg)
    # Both paragraphs fit in one chunk (10 + 10 = 20 <= 20)
    assert len(chunks) == 1


def test_custom_config():
    cfg = ChunkConfig(chunk_size=50, chunk_overlap=10, min_chunk_size=5)
    words = [f"tok{i}" for i in range(200)]
    text = " ".join(words)
    chunks = chunk_text(text, config=cfg)
    # Should produce multiple chunks
    assert len(chunks) >= 3


def test_short_only_document_not_dropped():
    """A whole document below min_chunk_size must still produce a chunk.

    Regression for #502 follow-up: previously a folder of short notes indexed
    to ``chunks_indexed: 0`` (HTTP 200), silently storing nothing. ``min_chunk_size``
    should only discard tiny *trailing fragments*, never an entire short doc.
    """
    cfg = ChunkConfig(chunk_size=100, chunk_overlap=0, min_chunk_size=50)
    # 30 words is below min_chunk_size=50, but it's the entire document.
    words = [f"w{i}" for i in range(30)]
    text = " ".join(words)
    chunks = chunk_text(text, config=cfg)
    assert len(chunks) == 1
    assert chunks[0].content == text


def test_short_real_world_note_not_dropped():
    """The exact repro from the issue: a ~4-word note must not vanish."""
    chunks = chunk_text("hello world\nsome content\n", source="a.txt")
    assert len(chunks) == 1
    assert "hello world" in chunks[0].content


def test_min_chunk_size_filters_tiny_trailing_fragment():
    """A tiny fragment trailing a real chunk is still dropped by the floor."""
    cfg = ChunkConfig(chunk_size=50, chunk_overlap=0, min_chunk_size=10)
    # Two paragraphs: the first fills a real chunk, the second is a tiny tail.
    para1 = " ".join(f"a{i}" for i in range(50))
    para2 = " ".join(f"b{i}" for i in range(3))  # 3 words < min_chunk_size=10
    text = f"{para1}\n\n{para2}"
    chunks = chunk_text(text, config=cfg)
    # The 3-word trailing fragment is discarded; only the real chunk remains.
    assert len(chunks) == 1
    assert "b0" not in chunks[0].content


def test_short_lead_in_before_oversized_paragraph_is_not_dropped():
    """A sub-floor lead-in must be carried into an oversized window (#754)."""
    lead_in = "IMPORTANT my API key rotation policy is documented here"
    large_paragraph = " ".join(f"word{i}" for i in range(600))

    chunks = chunk_text(f"{lead_in}\n\n{large_paragraph}")

    assert any(lead_in in chunk.content for chunk in chunks)
    output_tokens = {token for chunk in chunks for token in chunk.content.split()}
    assert set(lead_in.split()).issubset(output_tokens)
    assert {f"word{i}" for i in range(600)}.issubset(output_tokens)


def test_short_paragraph_before_full_normal_paragraph_is_not_dropped():
    """The ordinary paragraph-boundary flush also preserves sub-floor text."""
    cfg = ChunkConfig(chunk_size=10, chunk_overlap=0, min_chunk_size=5)
    short = "keep every word"
    full = " ".join(f"next{i}" for i in range(10))

    chunks = chunk_text(f"{short}\n\n{full}", config=cfg)

    assert any(short in chunk.content for chunk in chunks)
    assert set(short.split()) | set(full.split()) == {
        token for chunk in chunks for token in chunk.content.split()
    }
    assert all(len(chunk.content.split()) <= cfg.chunk_size for chunk in chunks)


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap", "min_chunk_size", "lead_size", "body_size"),
    [
        (10, 0, 5, 3, 10),
        (10, 2, 5, 3, 10),
        (8, 7, 6, 2, 8),
        (7, 0, 4, 3, 12),
        (16, 4, 8, 4, 33),
    ],
)
def test_preserved_short_lead_in_never_breaks_hard_chunk_bound(
    chunk_size, chunk_overlap, min_chunk_size, lead_size, body_size
):
    """Adversarial boundaries preserve every token in bounded chunks."""
    cfg = ChunkConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size,
    )
    lead = [f"lead{i}" for i in range(lead_size)]
    body = [f"body{i}" for i in range(body_size)]

    chunks = chunk_text(
        f"{' '.join(lead)}\n\n{' '.join(body)}",
        config=cfg,
    )

    output_tokens = {token for chunk in chunks for token in chunk.content.split()}
    assert set(lead + body).issubset(output_tokens)
    assert all(0 < len(chunk.content.split()) <= chunk_size for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_source_propagated():
    words = [f"word{i}" for i in range(60)]
    text = " ".join(words)
    chunks = chunk_text(text, source="myfile.md")
    assert len(chunks) == 1
    assert chunks[0].source == "myfile.md"


def test_chunk_index_sequential():
    cfg = ChunkConfig(chunk_size=50, chunk_overlap=0, min_chunk_size=5)
    words = [f"w{i}" for i in range(200)]
    text = " ".join(words)
    chunks = chunk_text(text, config=cfg)
    for i, chunk in enumerate(chunks):
        assert chunk.index == i
