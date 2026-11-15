"""Tests for document ingestion and file type detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.tools.storage.ingest import (
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


# ---------------------------------------------------------------------------
# .docx and other binary files
# ---------------------------------------------------------------------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_docx(path: Path, body_xml: str) -> None:
    """Write a minimal .docx: a zip archive holding word/document.xml."""
    import zipfile

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body_xml}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", document)


def _p(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def test_detect_file_type_docx(tmp_path: Path):
    assert detect_file_type(tmp_path / "Report.DOCX") == "docx"


def test_read_document_docx(tmp_path: Path):
    p = tmp_path / "contract.docx"
    split_run = (
        "<w:p><w:r><w:t>Split </w:t></w:r><w:r><w:t>across runs</w:t></w:r></w:p>"
    )
    table = (
        "<w:tbl><w:tr>"
        f"<w:tc>{_p('Item')}</w:tc><w:tc>{_p('Price')}</w:tc>"
        "</w:tr></w:tbl>"
    )
    _make_docx(p, _p("Service agreement") + _p("") + split_run + table)

    text, meta = read_document(p)

    assert meta.file_type == "docx"
    # One block per paragraph, runs joined, empty paragraphs dropped.
    assert text.split("\n\n") == [
        "Service agreement",
        "Split across runs",
        "Item",
        "Price",
    ]


def test_read_document_docx_invalid_raises_oserror(tmp_path: Path):
    p = tmp_path / "broken.docx"
    p.write_bytes(b"this is not a zip archive")
    with pytest.raises(OSError):
        read_document(p)


def test_ingest_directory_reads_docx_text(tmp_path: Path):
    """A .docx is indexed as its text, not as the bytes of the zip archive."""
    _make_docx(tmp_path / "notes.docx", _p("Quarterly planning notes"))
    (tmp_path / "plain.txt").write_text("plain text file", encoding="utf-8")

    chunks = ingest_path(tmp_path)
    joined = "\n".join(c.content for c in chunks)

    assert "Quarterly planning notes" in joined
    assert "plain text file" in joined
    assert "word/document.xml" not in joined
    assert "PK" not in joined


def test_ingest_directory_skips_corrupt_docx(tmp_path: Path):
    (tmp_path / "broken.docx").write_bytes(b"not a zip archive")
    (tmp_path / "ok.txt").write_text("still indexed", encoding="utf-8")

    chunks = ingest_path(tmp_path)

    assert {Path(c.source).name for c in chunks} == {"ok.txt"}


def test_ingest_directory_skips_binary_files(tmp_path: Path):
    """Binary files with no reader are skipped, whatever their extension."""
    (tmp_path / "sheet.xlsx").write_bytes(b"PK\x03\x04\x14\x00\x06\x00 spreadsheet")
    (tmp_path / "legacy.doc").write_bytes(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32 + b"legacy document"
    )
    (tmp_path / "blob.dat").write_bytes(b"\x00\x01\x02 raw bytes")
    (tmp_path / "ok.md").write_text("# Heading\n\nreal content", encoding="utf-8")

    chunks = ingest_path(tmp_path)

    assert {Path(c.source).name for c in chunks} == {"ok.md"}


@pytest.mark.parametrize("damage", ["encrypted", "unsupported_compression", "deflate"])
def test_unreadable_docx_does_not_abort_directory_ingest(tmp_path: Path, damage):
    """Unreadable ZIP members fail as documents without stopping the folder."""
    import zipfile

    path = tmp_path / "unreadable.docx"
    _make_docx(path, _p("document content"))
    with zipfile.ZipFile(path) as archive:
        local = archive.getinfo("word/document.xml").header_offset
        central_start = archive.start_dir
    data = bytearray(path.read_bytes())
    central = data.index(b"word/document.xml", central_start) - 46
    assert data[central : central + 4] == b"PK\x01\x02"
    if damage == "encrypted":
        data[local + 6] |= 1
        data[central + 8] |= 1
    elif damage == "unsupported_compression":
        data[local + 8 : local + 10] = (99).to_bytes(2, "little")
        data[central + 10 : central + 12] = (99).to_bytes(2, "little")
    else:
        name_length = int.from_bytes(data[local + 26 : local + 28], "little")
        extra_length = int.from_bytes(data[local + 28 : local + 30], "little")
        # A DEFLATE block with reserved type 3 cannot be decompressed.
        data[local + 30 + name_length + extra_length] = 7
    path.write_bytes(data)
    (tmp_path / "ok.txt").write_text("still indexed", encoding="utf-8")

    with pytest.raises(OSError, match="Not a readable .docx"):
        read_document(path)
    assert {Path(c.source).name for c in ingest_path(tmp_path)} == {"ok.txt"}


def test_docx_size_limit_skips_document_and_keeps_other_files(tmp_path, monkeypatch):
    path = tmp_path / "oversized.docx"
    _make_docx(path, _p("body exceeds the configured limit"))
    monkeypatch.setattr("openjarvis.tools.storage.ingest._DOCX_MAX_XML_BYTES", 32)
    (tmp_path / "ok.txt").write_text("still indexed", encoding="utf-8")

    with pytest.raises(OSError, match="too large"):
        read_document(path)
    assert {Path(c.source).name for c in ingest_path(tmp_path)} == {"ok.txt"}
