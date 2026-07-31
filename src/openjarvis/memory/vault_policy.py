"""Code-owned trust and retrieval policy for Markdown-vault note types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NoteType(str, Enum):
    """Closed set of supported canonical and legacy-compatible note types."""

    FACT = "fact"
    PREFERENCE = "preference"
    PROJECT = "project"
    DECISION = "decision"
    TASK = "task"
    EXPERIENCE = "experience"
    ERROR = "error"
    SOLUTION = "solution"
    SKILL = "skill"
    PERSON = "person"
    CAPTURE = "capture"
    REVIEW = "review"
    SYSTEM = "system"
    MEMORY_PROPOSAL = "memory_proposal"
    CATEGORY = "category"
    NAVIGATION = "navigation"
    PROJECT_PROFILE = "project_profile"
    SYSTEM_POLICY = "system_policy"
    SYSTEM_PROFILE = "system_profile"


class TrustClass(str, Enum):
    """Trust assigned by OpenJarvis, never by vault frontmatter."""

    SOURCE_BOUND = "source_bound"
    UNTRUSTED_PROPOSAL = "untrusted_proposal"
    STRUCTURAL = "structural"
    SCOPED_CONTEXT = "scoped_context"
    AUTHORITY_SENSITIVE_SOURCE = "authority_sensitive_source"
    UNCLASSIFIED = "unclassified"


class RetrievalClass(str, Enum):
    """Retrieval boundary assigned by OpenJarvis."""

    NORMAL = "normal"
    REVIEW_ONLY = "review_only"
    TAXONOMY_ONLY = "taxonomy_only"
    NAVIGATION_ONLY = "navigation_only"
    PROJECT_SCOPED = "project_scoped"
    EXPLICIT_REVIEW_ONLY = "explicit_review_only"
    REJECTED = "rejected"


class AuthorityClass(str, Enum):
    """Runtime authority a vault note is permitted to possess."""

    NONE = "none"
    PROHIBITED_RUNTIME_AUTHORITY = "prohibited_runtime_authority"


class ScopeClass(str, Enum):
    """How a retrieval scope must be interpreted."""

    DECLARED = "declared"
    REVIEW_ONLY = "review_only"
    STRUCTURAL = "structural"
    EXACT_PROJECT = "exact_project"
    EXPLICIT_REVIEW_ONLY = "explicit_review_only"
    UNCLASSIFIED = "unclassified"


class RetrievalPurpose(str, Enum):
    """Code-selected query purpose; callers cannot elevate a normal search."""

    NORMAL = "normal"
    EXPLICIT_REVIEW = "explicit_review"
    VAULT_STRUCTURE = "vault_structure"


@dataclass(frozen=True, slots=True)
class NoteSecurityClassification:
    """Non-overridable security classification for one supported note type."""

    trust_class: TrustClass
    retrieval_class: RetrievalClass
    authority_class: AuthorityClass
    scope_class: ScopeClass

    @property
    def retrieval_eligible(self) -> bool:
        """Return whether the note may enter ordinary unscoped memory retrieval."""

        return self.retrieval_class is RetrievalClass.NORMAL


_CANONICAL_NORMAL = {
    NoteType.FACT,
    NoteType.PREFERENCE,
    NoteType.PROJECT,
    NoteType.DECISION,
    NoteType.TASK,
    NoteType.EXPERIENCE,
    NoteType.ERROR,
    NoteType.SOLUTION,
    NoteType.SKILL,
    NoteType.PERSON,
    NoteType.CAPTURE,
    NoteType.REVIEW,
}

_NORMAL = NoteSecurityClassification(
    trust_class=TrustClass.SOURCE_BOUND,
    retrieval_class=RetrievalClass.NORMAL,
    authority_class=AuthorityClass.NONE,
    scope_class=ScopeClass.DECLARED,
)

_POLICY: dict[NoteType, NoteSecurityClassification] = {
    **{note_type: _NORMAL for note_type in _CANONICAL_NORMAL},
    NoteType.MEMORY_PROPOSAL: NoteSecurityClassification(
        trust_class=TrustClass.UNTRUSTED_PROPOSAL,
        retrieval_class=RetrievalClass.REVIEW_ONLY,
        authority_class=AuthorityClass.NONE,
        scope_class=ScopeClass.REVIEW_ONLY,
    ),
    NoteType.CATEGORY: NoteSecurityClassification(
        trust_class=TrustClass.STRUCTURAL,
        retrieval_class=RetrievalClass.TAXONOMY_ONLY,
        authority_class=AuthorityClass.NONE,
        scope_class=ScopeClass.STRUCTURAL,
    ),
    NoteType.NAVIGATION: NoteSecurityClassification(
        trust_class=TrustClass.STRUCTURAL,
        retrieval_class=RetrievalClass.NAVIGATION_ONLY,
        authority_class=AuthorityClass.NONE,
        scope_class=ScopeClass.STRUCTURAL,
    ),
    NoteType.PROJECT_PROFILE: NoteSecurityClassification(
        trust_class=TrustClass.SCOPED_CONTEXT,
        retrieval_class=RetrievalClass.PROJECT_SCOPED,
        authority_class=AuthorityClass.NONE,
        scope_class=ScopeClass.EXACT_PROJECT,
    ),
}

_AUTHORITY_SENSITIVE = NoteSecurityClassification(
    trust_class=TrustClass.AUTHORITY_SENSITIVE_SOURCE,
    retrieval_class=RetrievalClass.EXPLICIT_REVIEW_ONLY,
    authority_class=AuthorityClass.PROHIBITED_RUNTIME_AUTHORITY,
    scope_class=ScopeClass.EXPLICIT_REVIEW_ONLY,
)
for _note_type in (
    NoteType.SYSTEM,
    NoteType.SYSTEM_POLICY,
    NoteType.SYSTEM_PROFILE,
):
    _POLICY[_note_type] = _AUTHORITY_SENSITIVE

_REJECTED = NoteSecurityClassification(
    trust_class=TrustClass.UNCLASSIFIED,
    retrieval_class=RetrievalClass.REJECTED,
    authority_class=AuthorityClass.PROHIBITED_RUNTIME_AUTHORITY,
    scope_class=ScopeClass.UNCLASSIFIED,
)

NOTE_TYPES = frozenset(item.value for item in NoteType)
WRITABLE_NOTE_TYPES = frozenset(item.value for item in _CANONICAL_NORMAL)


def classify_note_type(note_type: str) -> NoteSecurityClassification:
    """Classify an exact note type, failing closed for unknown values."""

    try:
        parsed = NoteType(note_type)
    except ValueError:
        return _REJECTED
    return _POLICY[parsed]


__all__ = [
    "AuthorityClass",
    "NOTE_TYPES",
    "NoteSecurityClassification",
    "NoteType",
    "RetrievalClass",
    "RetrievalPurpose",
    "ScopeClass",
    "TrustClass",
    "WRITABLE_NOTE_TYPES",
    "classify_note_type",
]
