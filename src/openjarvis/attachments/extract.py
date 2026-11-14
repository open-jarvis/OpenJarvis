"""Turn an attached file into text Jarvis can read.

Supported: plain text and code, CSV/JSON, PDF (``pypdf``), Word ``.docx``
(``python-docx``) and Excel ``.xlsx`` (``openpyxl``). Images have no text of
their own; the library asks a vision model to describe them instead.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = frozenset(
    ".txt .md .markdown .csv .tsv .json .jsonl .log .xml .html .htm .css .js .jsx "
    ".ts .tsx .py .java .c .cpp .h .cs .go .rs .rb .php .sh .ps1 .bat .sql .yaml "
    ".yml .toml .ini .cfg .rtf".split()
)
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS

_MAX_SHEET_ROWS = 500


@dataclass(frozen=True)
class Extracted:
    text: str
    pages: Optional[int] = None
    error: str = ""


def kind_for(ext: str) -> str:
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return "text"


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace")


def _pdf(data: bytes) -> Extracted:
    try:
        from pypdf import PdfReader
    except ImportError:
        return Extracted("", error="Reading PDFs needs the 'pypdf' package.")
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return Extracted("", error="This PDF is password-protected.")
    parts = []
    has_text = False
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        has_text = has_text or bool(text)
        parts.append(f"--- Page {number} ---\n{text}")
    if not has_text:
        return Extracted(
            "",
            pages=len(reader.pages),
            error="No selectable text (it may be a scanned PDF).",
        )
    return Extracted("\n\n".join(parts), pages=len(reader.pages))


def _docx(data: bytes) -> Extracted:
    try:
        from docx import Document
    except ImportError:
        return Extracted("", error="Reading Word files needs 'python-docx'.")
    doc = Document(io.BytesIO(data))
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    for t_index, table in enumerate(doc.tables, start=1):
        lines.append(f"\n[Table {t_index}]")
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return Extracted("\n".join(lines))


def _xlsx(data: bytes) -> Extracted:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return Extracted("", error="Reading Excel files needs 'openpyxl'.")
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        parts = []
        for ws in wb.worksheets:
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= _MAX_SHEET_ROWS:
                    rows.append("… (more rows not shown)")
                    break
                if any(v is not None for v in row):
                    rows.append(",".join("" if v is None else str(v) for v in row))
            parts.append(f"--- Sheet: {ws.title} ---\n" + "\n".join(rows))
        return Extracted("\n\n".join(parts), pages=len(wb.worksheets))
    finally:
        wb.close()


def extract_text(data: bytes, ext: str) -> Extracted:
    """Extract readable text from *data*; images return empty text."""
    ext = ext.lower()
    try:
        if ext == ".pdf":
            return _pdf(data)
        if ext == ".docx":
            return _docx(data)
        if ext == ".xlsx":
            return _xlsx(data)
        if ext in IMAGE_EXTENSIONS:
            return Extracted("")
        return Extracted(_decode(data))
    except Exception as exc:  # corrupt or unusual files
        logger.info("Text extraction failed for %s: %s", ext, exc)
        return Extracted("", error=f"Could not read this file: {exc}")


__all__ = [
    "ALLOWED_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
    "Extracted",
    "IMAGE_EXTENSIONS",
    "TEXT_EXTENSIONS",
    "extract_text",
    "kind_for",
]
