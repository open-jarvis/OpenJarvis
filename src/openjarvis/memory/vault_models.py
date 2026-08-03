"""Canonical models for reconstructible Markdown-vault memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from openjarvis.memory.vault_policy import (
    NOTE_TYPES,
    AuthorityClass,
    RetrievalClass,
    ScopeClass,
    TrustClass,
)


class ConflictState(str, Enum):
    """Conflict state attached to a note or write candidate."""

    NONE = "none"
    DUPLICATE = "duplicate"
    POSSIBLE_CONFLICT = "possible_conflict"
    CONFIRMED_CONFLICT = "confirmed_conflict"
    EXTERNALLY_MODIFIED = "externally_modified"
    INVALID_SCHEMA = "invalid_schema"


class EvidenceStatus(str, Enum):
    """Quality of the evidence selected for an answer."""

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


class IdentityKind(str, Enum):
    """Origin and durability of a note identity."""

    STABLE = "stable"
    PROVISIONAL = "provisional"


class CandidateStatus(str, Enum):
    """Lifecycle state for a proposed Markdown write."""

    PROPOSED = "proposed"
    # Legacy values remain readable so existing vault indexes can be migrated
    # without losing their audit history. New Flow sessions do not create them.
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    CONFLICTED = "conflicted"
    EXPIRED = "expired"


SOURCE_PRIORITY: Mapping[str, int] = {
    "user_correction": 5,
    "confirmed": 4,
    "user": 3,
    "manual": 3,
    "verified_import": 2,
    "imported": 2,
    "inferred": 1,
    "auto": 1,
    "legacy": 0,
}


@dataclass(slots=True)
class MemoryNote:
    """One canonical, human-readable Markdown note."""

    note_id: str
    path: str
    title: str
    note_type: str
    status: str
    scope: str
    project: str | None
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    source: str
    source_task_id: str | None
    source_session_id: str | None
    created_at: str | None
    updated_at: str | None
    content_hash: str
    frontmatter_version: int | None
    body: str
    outgoing_links: tuple[str, ...] = ()
    backlinks: tuple[str, ...] = ()
    folder_relations: tuple[str, ...] = ()
    archived: bool = False
    conflict_state: ConflictState = ConflictState.NONE
    identity_kind: IdentityKind = IdentityKind.STABLE
    indexed_at: str | None = None
    modified_ns: int = 0
    size_bytes: int = 0
    body_start_line: int = 1
    raw_frontmatter: Mapping[str, Any] = field(default_factory=dict)
    parser_error: str | None = None
    frontmatter_parsed: bool = True
    schema_valid: bool = True
    type_supported: bool = True
    content_indexed: bool = False
    retrieval_eligible: bool = True
    trust_class: TrustClass = TrustClass.SOURCE_BOUND
    retrieval_class: RetrievalClass = RetrievalClass.NORMAL
    authority_class: AuthorityClass = AuthorityClass.NONE
    scope_class: ScopeClass = ScopeClass.DECLARED
    scope_binding: str | None = None

    @property
    def parse_status(self) -> str:
        """Return a stable API status distinct from physical discovery."""

        return "valid" if self.schema_valid and self.type_supported else "rejected"

    @property
    def is_provisional(self) -> bool:
        """Return whether this is a read-only legacy identity."""

        return self.identity_kind is IdentityKind.PROVISIONAL


@dataclass(frozen=True, slots=True)
class MemorySource:
    """A bounded note span actually selected as evidence."""

    source_id: str
    retrieval_id: str
    note_id: str
    path: str
    title: str
    relevant_text: str
    line_start: int | None
    line_end: int | None
    section: str | None
    score: float
    selection_reason: str
    content_hash: str
    indexed_at: str
    note_type: str
    trust_class: str
    retrieval_class: str
    authority_class: str
    scope_class: str


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """One bounded candidate considered during retrieval."""

    note_id: str
    path: str
    title: str
    score: float
    reason: str
    content_hash: str
    conflict_state: ConflictState
    source_priority: int
    note_type: str
    trust_class: str
    retrieval_class: str
    authority_class: str
    scope_class: str


@dataclass(frozen=True, slots=True)
class MemoryRetrievalResult:
    """Structured retrieval result with exact selected sources."""

    retrieval_id: str
    query: str
    normalized_query: str
    candidates: tuple[RetrievalCandidate, ...]
    selected_sources: tuple[MemorySource, ...]
    confidence: float
    evidence_status: EvidenceStatus
    retrieval_method: str
    filters: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    retrieval_purpose: str = "normal"

    @property
    def evidence_code(self) -> str:
        """Return the explicit machine-readable insufficiency marker."""

        if self.evidence_status is EvidenceStatus.INSUFFICIENT:
            return "insufficient_evidence"
        return self.evidence_status.value


@dataclass(frozen=True, slots=True)
class IndexReport:
    """Summary of a full or incremental vault index pass."""

    run_id: str
    mode: str
    started_at: str
    completed_at: str
    scanned: int
    indexed: int
    created: int
    modified: int
    moved: int
    deleted: int
    unchanged: int
    parser_errors: int
    duplicate_ids: int
    duplicate_contents: int
    conflicts: int
    warnings: tuple[str, ...] = ()
    discovered: int = 0
    frontmatter_parsed: int = 0
    schema_valid: int = 0
    type_supported: int = 0
    content_indexed: int = 0
    retrieval_eligible: int = 0
    review_only: int = 0
    structural: int = 0
    authority_sensitive: int = 0
    rejected: int = 0


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """Persistent proposal that must be approved before a Markdown write."""

    candidate_id: str
    task_id: str
    session_id: str
    correlation_id: str
    note_id: str
    proposed_path: str
    note_type: str
    scope: str
    project: str | None
    source: str
    body: str
    planned_markdown: str
    planned_diff: str
    before_hash: str | None
    expected_version: str | None
    risk_level: int
    status: CandidateStatus
    approval_id: str | None
    conflict_state: ConflictState
    created_at: str
    updated_at: str
    applied_at: str | None = None
    write_operation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryConflict:
    """One visible, non-silent conflict between memory records."""

    conflict_id: str
    conflict_type: str
    state: ConflictState
    note_ids: tuple[str, ...]
    candidate_id: str | None
    summary: str
    winner_note_id: str | None
    resolution: str | None
    created_at: str
    updated_at: str
    resolved_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryHealth:
    """Privacy-safe operational status for the vault memory service."""

    vault_configured: bool
    vault_reachable: bool
    mode: str
    index_available: bool
    fts5_available: bool
    note_count: int
    parser_error_count: int
    last_successful_index: str | None
    last_error: str | None
    embeddings_enabled: bool
    retrieval_mode: str
    open_candidates: int
    open_conflicts: int
    discovered_count: int = 0
    frontmatter_parsed_count: int = 0
    schema_valid_count: int = 0
    type_supported_count: int = 0
    fts_document_count: int = 0
    retrieval_eligible_count: int = 0
    review_only_count: int = 0
    structural_count: int = 0
    authority_sensitive_count: int = 0
    rejected_count: int = 0


__all__ = [
    "CandidateStatus",
    "ConflictState",
    "EvidenceStatus",
    "IdentityKind",
    "IndexReport",
    "MemoryCandidate",
    "MemoryConflict",
    "MemoryHealth",
    "MemoryNote",
    "MemoryRetrievalResult",
    "MemorySource",
    "NOTE_TYPES",
    "RetrievalCandidate",
    "SOURCE_PRIORITY",
]
