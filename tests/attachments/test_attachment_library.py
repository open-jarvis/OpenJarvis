"""Tests for the attachment library, text extraction and blob release."""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import pytest

from openjarvis.attachments.extract import extract_text
from openjarvis.attachments.library import AttachmentError, AttachmentLibrary
from openjarvis.connectors.attachment_store import AttachmentStore
from openjarvis.tools.attachment_tools import ListAttachmentsTool, ReadAttachmentTool


@pytest.fixture()
def lib(tmp_path: Path) -> AttachmentLibrary:
    return AttachmentLibrary(tmp_path / "att", AttachmentStore(str(tmp_path / "blobs")))


def test_text_and_code_files(lib: AttachmentLibrary) -> None:
    att = lib.add(b"print('hi')\n", "script.py")
    assert att.kind == "text" and att.status == "ready"
    assert lib.text(att.id) == "print('hi')\n"


def test_docx_and_xlsx_extraction() -> None:
    docx = pytest.importorskip("docx")
    openpyxl = pytest.importorskip("openpyxl")
    d = docx.Document()
    d.add_paragraph("Invoice 4471 total 12,500")
    buf = io.BytesIO()
    d.save(buf)
    assert "Invoice 4471" in extract_text(buf.getvalue(), ".docx").text

    wb = openpyxl.Workbook()
    wb.active.append(["Month", "Spend"])
    wb.active.append(["Oct", 4200])
    buf = io.BytesIO()
    wb.save(buf)
    out = extract_text(buf.getvalue(), ".xlsx")
    assert "Oct,4200" in out.text and out.pages == 1


def test_rejects_unsupported_empty_and_oversized(lib: AttachmentLibrary, monkeypatch) -> None:
    with pytest.raises(AttachmentError):
        lib.add(b"MZ", "tool.exe")
    with pytest.raises(AttachmentError):
        lib.add(b"", "empty.txt")
    import openjarvis.attachments.library as library

    monkeypatch.setattr(library, "MAX_FILE_BYTES", 10)
    with pytest.raises(AttachmentError):
        lib.add(b"x" * 11, "big.txt")


def test_find_list_and_delete_releases_blob(lib: AttachmentLibrary, tmp_path: Path) -> None:
    a = lib.add(b"alpha", "notes-alpha.txt")
    b = lib.add(b"alpha", "copy.txt")  # same bytes -> shared blob
    assert lib.find(a.id).id == a.id
    assert lib.find("notes-alpha.txt").id == a.id
    assert {x.id for x in lib.list()} == {a.id, b.id}
    blob = tmp_path / "blobs" / a.sha256[:2] / a.sha256
    assert lib.delete(a.id) is True
    assert blob.exists()  # still used by the copy
    assert lib.delete(b.id) is True
    assert not blob.exists()
    assert lib.get(a.id) is None


def test_image_is_described_in_background(tmp_path: Path) -> None:
    done = threading.Event()

    def describer(data: bytes, mime: str) -> str:
        done.set()
        return "A red square with the text HELLO."

    lib = AttachmentLibrary(
        tmp_path / "att", AttachmentStore(str(tmp_path / "blobs")), describer=describer
    )
    att = lib.add(b"\x89PNG\r\n\x1a\nfake", "shot.png", source="screenshot")
    assert att.kind == "image" and att.status == "describing"
    assert done.wait(5)
    for _ in range(100):
        if lib.get(att.id).status == "ready":
            break
        time.sleep(0.05)
    assert lib.get(att.id).status == "ready"
    assert "HELLO" in lib.text(att.id)


def test_context_for_truncates_and_points_to_tool(lib: AttachmentLibrary) -> None:
    att = lib.add(("word " * 2000).encode(), "long.txt")
    ctx = lib.context_for([att.id], budget_chars=1500)
    assert '"long.txt"' in ctx
    assert "read_attachment" in ctx and "truncated" in ctx
    assert lib.context_for(["000000000000"]) == ""


def test_tools_read_in_pages(lib: AttachmentLibrary, monkeypatch) -> None:
    import openjarvis.attachments.library as library

    monkeypatch.setattr(library, "_LIBRARY", lib)
    att = lib.add(("x" * 9000).encode(), "big-notes.txt")
    assert att.id in ListAttachmentsTool().execute(query="big").content
    first = ReadAttachmentTool().execute(attachment="big-notes")
    assert first.success and "offset=8000" in first.content
    rest = ReadAttachmentTool().execute(attachment=att.id, offset=8000)
    assert rest.success and "[end of attachment]" in rest.content
