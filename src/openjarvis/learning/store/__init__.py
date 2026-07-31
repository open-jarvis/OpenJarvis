"""Persistent, append-only learning store API."""

from openjarvis.learning.store.models import (
    AuditEvent,
    AuditEventType,
    CandidateHead,
    CandidateIngestOutcome,
    CandidateRevisionRecord,
    IngestDisposition,
    IngestOutcome,
    PersistedConflictLink,
    PersistedDuplicateLink,
)
from openjarvis.learning.store.repository import (
    ExpectedRevisionError,
    IdempotencyConflictError,
    LearningIntegrityError,
    LearningRecordNotFoundError,
    LearningRepository,
    LearningStoreError,
)
from openjarvis.learning.store.sqlite import (
    MigrationIntegrityError,
    SQLiteLearningDatabase,
)

__all__ = [
    "AuditEvent",
    "AuditEventType",
    "CandidateHead",
    "CandidateIngestOutcome",
    "CandidateRevisionRecord",
    "ExpectedRevisionError",
    "IdempotencyConflictError",
    "IngestDisposition",
    "IngestOutcome",
    "LearningIntegrityError",
    "LearningRecordNotFoundError",
    "LearningRepository",
    "LearningStoreError",
    "MigrationIntegrityError",
    "PersistedConflictLink",
    "PersistedDuplicateLink",
    "SQLiteLearningDatabase",
]
