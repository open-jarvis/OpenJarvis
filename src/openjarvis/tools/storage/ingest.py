"""Document ingestion — file reading, type detection, directory walking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

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
    """Map a file extension to one of: text, markdown, pdf, code."""
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".mdx"}:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
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

        try:
            text, _meta = read_document(child)
            chunks = chunk_text(text, source=str(child), config=config)
            all_chunks.extend(chunks)
        except (ImportError, OSError):
            # Skip files we can't read (e.g. PDF without pdfplumber)
            continue

    return all_chunks


__all__ = ["DocumentMeta", "detect_file_type", "ingest_path", "read_document"]
