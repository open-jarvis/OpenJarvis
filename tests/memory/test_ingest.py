"""Tests for document ingestion and file type detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from friday_ai.tools.storage.ingest import (
    detect_file_type,
    ingest_path,
    read_document,
)


def test_detect_file_type_markdown(tmp_path: Path):
    p = tmp_path / "readme.md"
    assert detect_file_type(p) == "markdown"
    p2 = tmp_path / "doc.markdown"
    assert detect_file_type(p2) == "markdown"


def test_detect_file_type_python(tmp_path: Path):
    p = tmp_path / "main.py"
    assert detect_file_type(p) == "code"


def test_detect_file_type_pdf(tmp_path: Path):
    p = tmp_path / "paper.pdf"
    assert detect_file_type(p) == "pdf"


def test_detect_file_type_unknown(tmp_path: Path):
    p = tmp_path / "notes.txt"
    assert detect_file_type(p) == "text"
    p2 = tmp_path / "data.csv"
    assert detect_file_type(p2) == "text"


def test_read_document_text(tmp_path: Path):
    p = tmp_path / "hello.txt"
    p.write_text("Hello, world!\nLine two.", encoding="utf-8")
    text, meta = read_document(p)
    assert "Hello, world!" in text
    assert meta.file_type == "text"
    assert meta.line_count == 2
    assert meta.size_bytes > 0


def test_read_document_utf8_fallback(tmp_path: Path):
    p = tmp_path / "latin.txt"
    p.write_bytes(b"caf\xe9 au lait")
    text, meta = read_document(p)
    assert "caf" in text


def test_read_document_pdf_missing_dep(tmp_path: Path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4 fake pdf content")
    # Should raise ImportError when pdfplumber not installed
    # or succeed if it IS installed — either way just check it's handled
    try:
        read_document(p)
    except ImportError as exc:
        assert "pdfplumber" in str(exc)


def test_read_document_not_found(tmp_path: Path):
    p = tmp_path / "nope.txt"
    with pytest.raises(FileNotFoundError):
        read_document(p)


def test_ingest_single_file(tmp_path: Path):
    p = tmp_path / "doc.txt"
    content = " ".join(f"word{i}" for i in range(100))
    p.write_text(content, encoding="utf-8")
    chunks = ingest_path(p)
    assert len(chunks) >= 1
    assert chunks[0].source == str(p)


def test_ingest_directory_recursive(tmp_path: Path):
    sub = tmp_path / "docs"
    sub.mkdir()
    (sub / "a.txt").write_text(
        " ".join(f"a{i}" for i in range(100)),
        encoding="utf-8",
    )
    (sub / "b.md").write_text(
        " ".join(f"b{i}" for i in range(100)),
        encoding="utf-8",
    )
    chunks = ingest_path(tmp_path)
    sources = {c.source for c in chunks}
    assert any("a.txt" in s for s in sources)
    assert any("b.md" in s for s in sources)


def test_ingest_skips_hidden_dirs(tmp_path: Path):
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.txt").write_text(
        " ".join(f"s{i}" for i in range(100)),
        encoding="utf-8",
    )
    (tmp_path / "visible.txt").write_text(
        " ".join(f"v{i}" for i in range(100)),
        encoding="utf-8",
    )
    chunks = ingest_path(tmp_path)
    sources = {c.source for c in chunks}
    assert not any(".hidden" in s for s in sources)


def test_ingest_skips_pycache(tmp_path: Path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-310.pyc").write_bytes(b"\x00\x00")
    (tmp_path / "real.py").write_text(
        " ".join(f"r{i}" for i in range(100)),
        encoding="utf-8",
    )
    chunks = ingest_path(tmp_path)
    sources = {c.source for c in chunks}
    assert not any("__pycache__" in s for s in sources)


def test_ingest_nonexistent_path(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ingest_path(tmp_path / "nope")


def test_ingest_empty_dir(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    chunks = ingest_path(empty)
    assert chunks == []


def test_ingest_skips_env_files(tmp_path: Path):
    (tmp_path / ".env").write_text(
        " ".join(f"x{i}" for i in range(100)), encoding="utf-8"
    )
    (tmp_path / "readme.txt").write_text(
        " ".join(f"x{i}" for i in range(100)), encoding="utf-8"
    )
    chunks = ingest_path(tmp_path)
    sources = {c.source for c in chunks}
    assert not any(".env" in s for s in sources)
    assert any("readme.txt" in s for s in sources)


def test_ingest_skips_key_files(tmp_path: Path):
    (tmp_path / "server.key").write_text(
        " ".join(f"x{i}" for i in range(100)), encoding="utf-8"
    )
    (tmp_path / "notes.txt").write_text(
        " ".join(f"x{i}" for i in range(100)), encoding="utf-8"
    )
    chunks = ingest_path(tmp_path)
    sources = {c.source for c in chunks}
    assert not any("server.key" in s for s in sources)
    assert any("notes.txt" in s for s in sources)


def test_ingest_processes_normal_files(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        " ".join(f"x{i}" for i in range(100)), encoding="utf-8"
    )
    (tmp_path / "doc.md").write_text(
        " ".join(f"x{i}" for i in range(100)), encoding="utf-8"
    )
    chunks = ingest_path(tmp_path)
    sources = {c.source for c in chunks}
    assert any("app.py" in s for s in sources)
    assert any("doc.md" in s for s in sources)
