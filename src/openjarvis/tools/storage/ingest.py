"""Document ingestion — file reading, type detection, directory walking."""

from __future__ import annotations

import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree import ElementTree

from openjarvis.tools.storage.chunking import Chunk, ChunkConfig, chunk_text

# Directories to skip when walking a tree
_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "__pypackages__",
        ".eggs",
        "*.egg-info",
    }
)

# Extension -> file-type mapping
_CODE_EXTS = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".rs",
        ".go",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rb",
        ".sh",
        ".bash",
        ".zsh",
        ".lua",
        ".swift",
        ".kt",
        ".scala",
        ".cs",
        ".r",
        ".sql",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".xml",
        ".html",
        ".css",
    }
)


@dataclass(slots=True)
class DocumentMeta:
    """Metadata about an ingested document."""

    path: str
    file_type: str
    size_bytes: int
    line_count: int


def detect_file_type(path: Path) -> str:
    """Map a file extension to one of: text, markdown, pdf, docx, code."""
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".mdx"}:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in _CODE_EXTS:
        return "code"
    return "text"


def read_document(path: Path) -> Tuple[str, DocumentMeta]:
    """Read a file and return ``(text, metadata)``.

    Raises
    ------
    ImportError
        If the file is a PDF and ``pdfplumber`` is not installed.
    FileNotFoundError
        If *path* does not exist.
    OSError
        If the file is a ``.docx`` that cannot be read as one.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ftype = detect_file_type(path)

    if ftype == "pdf":
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            raise ImportError(
                "PDF support requires pdfplumber. "
                "Install it with: uv sync --extra memory-pdf"
            ) from None

        text = _read_pdf(path)
    elif ftype == "docx":
        text = _read_docx(path)
    else:
        text = _read_text(path)

    line_count = text.count("\n") + 1 if text else 0
    meta = DocumentMeta(
        path=str(path),
        file_type=ftype,
        size_bytes=path.stat().st_size,
        line_count=line_count,
    )
    return text, meta


def _read_text(path: Path) -> str:
    """Read a text file with UTF-8, falling back to latin-1."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


# WordprocessingML namespace and the largest document.xml we are willing to
# inflate (a .docx is a zip archive, so the size on disk says little).
_DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DOCX_MAX_XML_BYTES = 64 * 1024 * 1024


def _read_docx(path: Path) -> str:
    """Extract the text of a .docx, one block per paragraph.

    Uses only the standard library: the body lives in ``word/document.xml``
    and every paragraph, including those inside table cells, is a ``w:p``.
    Raises ``OSError`` when the file is not a readable .docx so that callers
    can skip it like any other unreadable file.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _DOCX_MAX_XML_BYTES:
                raise OSError(f"Document body too large to read: {path}")
            root = ElementTree.fromstring(archive.read(info))
    except (
        zipfile.BadZipFile,
        KeyError,
        ElementTree.ParseError,
        RuntimeError,  # encrypted files or unsupported compression
        zlib.error,
    ) as exc:
        raise OSError(f"Not a readable .docx file: {path}") from exc

    paragraphs: List[str] = []
    for paragraph in root.iter(f"{_DOCX_NS}p"):
        pieces: List[str] = []
        for node in paragraph.iter():
            if node.tag == f"{_DOCX_NS}t":
                pieces.append(node.text or "")
            elif node.tag == f"{_DOCX_NS}tab":
                pieces.append("\t")
            elif node.tag in (f"{_DOCX_NS}br", f"{_DOCX_NS}cr"):
                pieces.append("\n")
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _looks_binary(path: Path) -> bool:
    """Return True when the start of the file contains NUL bytes.

    Text files do not; office documents, archives, databases, fonts and
    images do. Reading those as text indexes garbage.
    """
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(8192)
    except OSError:
        return True


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF via pdfplumber."""
    import pdfplumber

    pages: List[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def _should_skip_dir(name: str) -> bool:
    """Return True if directory *name* should be skipped."""
    if name.startswith("."):
        return True
    if name in _SKIP_DIRS:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def ingest_path(
    path: Path,
    *,
    config: Optional[ChunkConfig] = None,
) -> List[Chunk]:
    """Ingest a file or directory into chunks.

    If *path* is a file, reads and chunks it.
    If *path* is a directory, recursively walks it (skipping hidden and
    common non-content directories) and chunks each file.
    """
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_file():
        text, _meta = read_document(path)
        return chunk_text(text, source=str(path), config=config)

    # Directory: recursive walk
    all_chunks: List[Chunk] = []
    for child in sorted(path.rglob("*")):
        # Skip directories themselves — rglob yields files too
        if child.is_dir():
            continue

        # Check if any parent directory should be skipped
        rel = child.relative_to(path)
        skip = False
        for part in rel.parts[:-1]:
            if _should_skip_dir(part):
                skip = True
                break
        if skip:
            continue

        # Skip hidden files
        if child.name.startswith("."):
            continue

        # Skip sensitive files (secrets, credentials, keys)
        from openjarvis.security.file_policy import is_sensitive_file

        if is_sensitive_file(child):
            continue

        # Skip binary-looking files
        if child.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".ico",
            ".mp3",
            ".mp4",
            ".wav",
            ".avi",
            ".mov",
            ".zip",
            ".tar",
            ".gz",
            ".bz2",
            ".7z",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".o",
            ".pyc",
            ".pyo",
            ".class",
            ".wasm",
        }:
            continue

        # ...and binary files the extension list does not know about
        # (.xlsx, .pptx, .doc, databases, fonts): formats with a reader
        # are handled by read_document, anything else would be indexed as
        # garbage.
        if detect_file_type(child) not in {"pdf", "docx"} and _looks_binary(child):
            continue

        try:
            text, _meta = read_document(child)
            chunks = chunk_text(text, source=str(child), config=config)
            all_chunks.extend(chunks)
        except (ImportError, OSError):
            # Skip files we can't read (e.g. PDF without pdfplumber,
            # a corrupt .docx)
            continue

    return all_chunks


__all__ = ["DocumentMeta", "detect_file_type", "ingest_path", "read_document"]
