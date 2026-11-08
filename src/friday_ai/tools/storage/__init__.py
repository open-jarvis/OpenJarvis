"""Storage primitive — persistent searchable storage."""

from __future__ import annotations

# Always-available backend
import friday_ai.tools.storage.sqlite  # noqa: F401

# Optional backends — import to trigger registration
try:
    import friday_ai.tools.storage.bm25  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.storage.faiss_backend  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.storage.colbert_backend  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.storage.hybrid  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.storage.dense  # noqa: F401
except ImportError:
    pass

from friday_ai.tools.storage._stubs import MemoryBackend, RetrievalResult
from friday_ai.tools.storage.chunking import Chunk, ChunkConfig, chunk_text
from friday_ai.tools.storage.context import ContextConfig, inject_context
from friday_ai.tools.storage.ingest import ingest_path, read_document

__all__ = [
    "Chunk",
    "ChunkConfig",
    "ContextConfig",
    "MemoryBackend",
    "RetrievalResult",
    "chunk_text",
    "inject_context",
    "ingest_path",
    "read_document",
]
