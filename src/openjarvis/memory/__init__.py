"""Native persistent long-term memory for OpenJarvis.

This package provides the automatic memory service that extracts durable facts
from conversations in the background and persists them across sessions. It is
started and stopped as part of the ``jarvis serve`` / ``jarvis chat`` lifecycle
and configured via the ``[memory]`` section of ``config.toml``.
"""

from __future__ import annotations

from openjarvis.memory.candidates import (
    MemoryCandidateWorkflow,
    candidate_to_dict,
    has_memory_intent,
    recognize_memory_request,
)
from openjarvis.memory.extractor import FactExtractor
from openjarvis.memory.frontmatter import (
    FrontmatterError,
    ParsedMarkdown,
    load_memory_note,
    parse_markdown,
)
from openjarvis.memory.migration import (
    MigrationDryRunReport,
    MigrationFinding,
    PlannedMigrationChange,
    analyze_vault_migration,
)
from openjarvis.memory.safe_write import (
    AtomicMarkdownWriter,
    AtomicWriteResult,
    ConcurrentMemoryWrite,
    UnsafeMemoryPath,
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
from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
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
from openjarvis.memory.vault_policy import (
    AuthorityClass,
    NoteType,
    RetrievalClass,
    RetrievalPurpose,
    ScopeClass,
    TrustClass,
    classify_note_type,
)
from openjarvis.memory.vault_retrieval import VaultRetriever, normalize_query
from openjarvis.memory.vault_service import (
    VaultMemoryService,
    build_vault_memory_service,
)
from openjarvis.memory.vault_watcher import PollingVaultWatcher

__all__ = [
    "Fact",
    "FactStore",
    "FactExtractor",
    "FrontmatterError",
    "CandidateStatus",
    "AtomicMarkdownWriter",
    "AtomicWriteResult",
    "AuthorityClass",
    "ConflictState",
    "ConcurrentMemoryWrite",
    "EvidenceStatus",
    "IdentityKind",
    "IndexReport",
    "LocalFactStore",
    "MemoryCandidate",
    "MemoryCandidateWorkflow",
    "MemoryConflict",
    "MigrationDryRunReport",
    "MigrationFinding",
    "MemoryHealth",
    "MemoryNote",
    "MemoryRetrievalResult",
    "MemoryService",
    "MemorySource",
    "MemoryTaskBridge",
    "MemoryTaskContext",
    "NoteType",
    "ParsedMarkdown",
    "PlannedMigrationChange",
    "RetrievalCandidate",
    "RetrievalClass",
    "RetrievalPurpose",
    "ScopeClass",
    "TrustClass",
    "VaultIndex",
    "VaultMemoryService",
    "VaultRetriever",
    "PollingVaultWatcher",
    "UnsafeMemoryPath",
    "build_memory_service",
    "build_vault_memory_service",
    "analyze_vault_migration",
    "candidate_to_dict",
    "has_memory_intent",
    "classify_note_type",
    "create_fact_store",
    "load_memory_note",
    "parse_markdown",
    "normalize_query",
    "publish_completed_exchange",
    "recognize_memory_request",
]
