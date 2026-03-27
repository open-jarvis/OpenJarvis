"""Tests for AttachmentStore — content-addressed blob storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.connectors.attachment_store import AttachmentStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> AttachmentStore:
    return AttachmentStore(base_dir=str(tmp_path / "blobs"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_store_returns_sha256(store: AttachmentStore) -> None:
    """store() returns a 64-character lowercase hex string (SHA-256)."""
    sha = store.store(b"hello world", filename="hello.txt")
    assert isinstance(sha, str)
    assert len(sha) == 64
    assert sha == sha.lower()
    # Only hex characters
    int(sha, 16)


def test_store_creates_blob_file(store: AttachmentStore, tmp_path: Path) -> None:
    """Blob file is written at {base_dir}/{sha[:2]}/{sha} with correct content."""
    data = b"binary content for blob test"
    sha = store.store(data, filename="blob.bin", mime_type="application/octet-stream")

    blob_path = tmp_path / "blobs" / sha[:2] / sha
    assert blob_path.exists(), f"Expected blob at {blob_path}"
    assert blob_path.read_bytes() == data


def test_dedup_same_content(store: AttachmentStore) -> None:
    """Storing identical bytes twice returns the same hash."""
    data = b"duplicate content"
    sha1 = store.store(data, filename="file1.txt")
    sha2 = store.store(data, filename="file2.txt")
    assert sha1 == sha2


def test_dedup_tracks_multiple_sources(store: AttachmentStore) -> None:
    """Three stores of the same bytes accumulate three distinct source_doc_ids."""
    data = b"shared attachment content"
    store.store(data, filename="attach.pdf", source_doc_id="doc:001")
    store.store(data, filename="attach.pdf", source_doc_id="doc:002")
    store.store(data, filename="attach.pdf", source_doc_id="doc:003")

    sha = store.store(data, filename="attach.pdf")  # 4th call, no new source
    meta = store.get_metadata(sha)
    assert meta is not None
    source_ids = meta["source_doc_ids"]
    assert "doc:001" in source_ids
    assert "doc:002" in source_ids
    assert "doc:003" in source_ids
    assert len(source_ids) == 3  # no duplicates


def test_get_metadata(store: AttachmentStore) -> None:
    """get_metadata() returns correct filename, mime_type, and size_bytes."""
    data = b"metadata test payload"
    sha = store.store(
        data,
        filename="report.pdf",
        mime_type="application/pdf",
        source_doc_id="doc:meta:001",
    )

    meta = store.get_metadata(sha)
    assert meta is not None
    assert meta["sha256"] == sha
    assert meta["filename"] == "report.pdf"
    assert meta["mime_type"] == "application/pdf"
    assert meta["size_bytes"] == len(data)
    assert "created_at" in meta
    assert isinstance(meta["source_doc_ids"], list)


def test_get_content(store: AttachmentStore) -> None:
    """get_content() returns the exact bytes that were stored."""
    data = b"\x00\x01\x02\x03binary\xff\xfe"
    sha = store.store(data, filename="binary.bin")
    retrieved = store.get_content(sha)
    assert retrieved == data


def test_get_content_nonexistent(store: AttachmentStore) -> None:
    """get_content() returns None for an unknown SHA-256."""
    fake_sha = "a" * 64
    assert store.get_content(fake_sha) is None
