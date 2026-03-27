"""Tests for SemanticChunker — type-aware text splitting."""

from __future__ import annotations

import pytest

from openjarvis.connectors.chunker import ChunkResult, SemanticChunker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def chunker() -> SemanticChunker:
    return SemanticChunker(max_tokens=50)


# ---------------------------------------------------------------------------
# 1. Short message stays as single chunk
# ---------------------------------------------------------------------------


def test_short_message_single_chunk(chunker: SemanticChunker) -> None:
    """A message shorter than max_tokens is returned as a single chunk."""
    text = "Hello, world! How are you today?"
    results = chunker.chunk(text, doc_type="message")
    assert len(results) == 1
    assert results[0].content == text
    assert results[0].index == 0


# ---------------------------------------------------------------------------
# 2. Long document splits on ## Heading sections, metadata has section key
# ---------------------------------------------------------------------------


def test_document_splits_on_headings() -> None:
    """Documents with ## headings produce chunks with section metadata."""
    chunker = SemanticChunker(max_tokens=512)
    text = (
        "## Introduction\n"
        "This is the introduction paragraph. It explains the context.\n\n"
        "## Methods\n"
        "This section describes the methods used in the study.\n\n"
        "## Results\n"
        "Here are the results of the experiment."
    )
    results = chunker.chunk(text, doc_type="document")
    # Each ## section should produce at least one chunk
    sections = {r.metadata.get("section") for r in results}
    assert "Introduction" in sections
    assert "Methods" in sections
    assert "Results" in sections


# ---------------------------------------------------------------------------
# 3. Within a section, splits on paragraph boundaries
# ---------------------------------------------------------------------------


def test_document_splits_on_paragraphs() -> None:
    """Within a section, long content splits on double-newline paragraph breaks."""
    # Use a small max_tokens to force splitting within a section
    chunker = SemanticChunker(max_tokens=15)
    # Build a section with two paragraphs, each > 15 tokens
    para1 = " ".join(["word"] * 20)  # 20 tokens
    para2 = " ".join(["text"] * 20)  # 20 tokens
    text = f"## Section One\n{para1}\n\n{para2}"
    results = chunker.chunk(text, doc_type="document")
    # Both paragraphs should be separate chunks
    assert len(results) >= 2
    # All chunks from this section carry section metadata
    for r in results:
        assert r.metadata.get("section") == "Section One"


# ---------------------------------------------------------------------------
# 4. Never splits mid-sentence (chunks end with . ? or ! except possibly last)
# ---------------------------------------------------------------------------


def test_no_mid_sentence_splits() -> None:
    """Chunks (except possibly the last) must end with sentence-ending punctuation."""
    chunker = SemanticChunker(max_tokens=10)
    # Build text with clearly delimited sentences in a document section
    text = (
        "## Analysis\n"
        "The first result was positive. The second outcome was negative. "
        "The third finding was inconclusive. The final conclusion is pending."
    )
    results = chunker.chunk(text, doc_type="document")
    # All chunks except possibly the last should end with sentence punctuation
    for r in results[:-1]:
        stripped = r.content.rstrip()
        assert stripped[-1] in {".", "?", "!"}, (
            f"Non-final chunk does not end with sentence punctuation: {stripped!r}"
        )


# ---------------------------------------------------------------------------
# 5. Email thread splits on reply boundaries
# ---------------------------------------------------------------------------


def test_email_splits_on_reply_boundaries() -> None:
    """Emails split on 'On ... wrote:' reply headers."""
    chunker = SemanticChunker(max_tokens=512)
    text = (
        "Hi Alice, please see my comments below.\n\n"
        "On Mon, Jan 1, 2024, Alice Smith <alice@example.com> wrote:\n"
        "> Original message here.\n"
        "> More original text.\n\n"
        "On Sun, Dec 31, 2023, Bob Jones <bob@example.com> wrote:\n"
        "> Even earlier message content."
    )
    results = chunker.chunk(text, doc_type="email")
    # Should produce more than one chunk due to reply boundaries
    assert len(results) >= 2


# ---------------------------------------------------------------------------
# 6. Event stays as single chunk
# ---------------------------------------------------------------------------


def test_event_always_single_chunk() -> None:
    """Events are never split regardless of length."""
    chunker = SemanticChunker(max_tokens=5)
    text = " ".join(["word"] * 100)  # 100 tokens, well above max_tokens=5
    results = chunker.chunk(text, doc_type="event")
    assert len(results) == 1
    assert results[0].content == text


# ---------------------------------------------------------------------------
# 7. Contact stays as single chunk
# ---------------------------------------------------------------------------


def test_contact_always_single_chunk() -> None:
    """Contacts are never split regardless of length."""
    chunker = SemanticChunker(max_tokens=5)
    text = " ".join(["info"] * 100)  # 100 tokens, well above max_tokens=5
    results = chunker.chunk(text, doc_type="contact")
    assert len(results) == 1
    assert results[0].content == text


# ---------------------------------------------------------------------------
# 8. Parent metadata inherited to all chunks
# ---------------------------------------------------------------------------


def test_parent_metadata_inherited() -> None:
    """All chunks carry the parent metadata passed to chunk()."""
    chunker = SemanticChunker(max_tokens=10)
    parent_meta = {"source": "gmail", "doc_id": "abc-123", "priority": "high"}
    text = (
        "## Section A\n"
        "First sentence of section A. Second sentence of section A. "
        "Third sentence here. Fourth sentence concludes.\n\n"
        "## Section B\n"
        "First sentence of section B. Second sentence of section B."
    )
    results = chunker.chunk(text, doc_type="document", metadata=parent_meta)
    for r in results:
        assert r.metadata.get("source") == "gmail"
        assert r.metadata.get("doc_id") == "abc-123"
        assert r.metadata.get("priority") == "high"


# ---------------------------------------------------------------------------
# 9. Chunks have sequential 0-based indexes
# ---------------------------------------------------------------------------


def test_sequential_chunk_indexes() -> None:
    """Chunks are indexed sequentially from 0 across all splits."""
    chunker = SemanticChunker(max_tokens=10)
    text = (
        "## Alpha\n"
        "Sentence one ends here. Sentence two ends here. Sentence three ends here.\n\n"
        "## Beta\n"
        "Sentence four ends here. Sentence five ends here."
    )
    results = chunker.chunk(text, doc_type="document")
    for i, r in enumerate(results):
        assert r.index == i, f"Expected index {i}, got {r.index}"


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_note_doc_type_treated_as_document() -> None:
    """doc_type='note' uses the same document splitting strategy."""
    chunker = SemanticChunker(max_tokens=512)
    text = (
        "## My Note\n"
        "This is a note with section headings.\n\n"
        "## Another Section\n"
        "More content here."
    )
    results = chunker.chunk(text, doc_type="note")
    sections = {r.metadata.get("section") for r in results}
    assert "My Note" in sections
    assert "Another Section" in sections


def test_unknown_doc_type_treated_as_document() -> None:
    """Unknown doc_type uses the document splitting strategy."""
    chunker = SemanticChunker(max_tokens=512)
    text = "## Header\nContent under the header.\n\n"
    results = chunker.chunk(text, doc_type="unknown_type")
    sections = {r.metadata.get("section") for r in results}
    assert "Header" in sections


def test_empty_text_returns_empty_list() -> None:
    """Empty string input returns an empty list."""
    chunker = SemanticChunker(max_tokens=512)
    results = chunker.chunk("", doc_type="document")
    assert results == []


def test_whitespace_only_text_returns_empty_list() -> None:
    """Whitespace-only input returns an empty list."""
    chunker = SemanticChunker(max_tokens=512)
    results = chunker.chunk("   \n\n  \t  ", doc_type="document")
    assert results == []


def test_chunk_result_is_dataclass() -> None:
    """ChunkResult has the expected fields with correct defaults."""
    cr = ChunkResult(content="hello")
    assert cr.content == "hello"
    assert cr.index == 0
    assert cr.metadata == {}


def test_message_accumulates_into_max_tokens() -> None:
    """Message chunks accumulate paragraphs up to max_tokens."""
    chunker = SemanticChunker(max_tokens=20)
    # Each paragraph is 8 tokens; two fit in 20 but three would exceed 20 (8+8+8=24)
    para = "one two three four five six seven eight"  # 8 tokens
    text = f"{para}\n\n{para}\n\n{para}\n\n{para}"
    results = chunker.chunk(text, doc_type="message")
    # Should not fit all 4 paragraphs in one chunk (would be 32 tokens)
    assert len(results) >= 2
    # Each chunk should be within or just at max_tokens (greedy accumulation)
    for r in results[:-1]:
        assert len(r.content.split()) <= 20 * 2  # some flexibility for joining


def test_document_no_headings_uses_paragraphs() -> None:
    """Documents without ## headings fall back to paragraph splitting."""
    chunker = SemanticChunker(max_tokens=15)
    para1 = " ".join(["alpha"] * 20)  # 20 tokens, forces split
    para2 = " ".join(["beta"] * 20)
    text = f"{para1}\n\n{para2}"
    results = chunker.chunk(text, doc_type="document")
    assert len(results) >= 2
