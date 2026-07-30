"""Native persistent long-term memory for OpenJarvis.

This package provides the automatic memory service that extracts durable facts
from conversations in the background and persists them across sessions. It is
started and stopped as part of the ``jarvis serve`` / ``jarvis chat`` lifecycle
and configured via the ``[memory]`` section of ``config.toml``.
"""

from __future__ import annotations

from openjarvis.memory.extractor import FactExtractor
from openjarvis.memory.frontmatter import (
    FrontmatterError,
    ParsedMarkdown,
    load_memory_note,
    parse_markdown,
)
from openjarvis.memory.service import (
    MemoryService,
    build_memory_service,
    publish_completed_exchange,
)
from openjarvis.memory.store import (
    Fact,
    FactStore,
    LocalFactStore,
    create_fact_store,
)
from openjarvis.memory.vault_models import (
    CandidateStatus,
    ConflictState,
    EvidenceStatus,
    IdentityKind,
    IndexReport,
    MemoryCandidate,
    MemoryConflict,
    MemoryHealth,
    MemoryNote,
    MemoryRetrievalResult,
    MemorySource,
    RetrievalCandidate,
)

__all__ = [
    "Fact",
    "FactStore",
    "FactExtractor",
    "FrontmatterError",
    "CandidateStatus",
    "ConflictState",
    "EvidenceStatus",
    "IdentityKind",
    "IndexReport",
    "LocalFactStore",
    "MemoryCandidate",
    "MemoryConflict",
    "MemoryHealth",
    "MemoryNote",
    "MemoryRetrievalResult",
    "MemoryService",
    "MemorySource",
    "ParsedMarkdown",
    "RetrievalCandidate",
    "build_memory_service",
    "create_fact_store",
    "load_memory_note",
    "parse_markdown",
    "publish_completed_exchange",
]
