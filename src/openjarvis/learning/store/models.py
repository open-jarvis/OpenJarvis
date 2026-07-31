"""Immutable persistence records for the learning store."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.candidates.models import (
    CandidateScope,
    CandidateState,
    CandidateType,
    ConflictPriority,
    ConflictType,
    Digest,
    DuplicateReason,
    Identifier,
    LearningCandidate,
    ProposedDestination,
    ShortText,
)
from openjarvis.learning.lifecycle.models import ActorType, TransitionRecord


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


def _digest(payload: object) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AuditEventType(str, Enum):
    EVALUATION_PERSISTED = "evaluation.persisted"
    EXTRACTION_PERSISTED = "extraction.persisted"
    CANDIDATE_CREATED = "candidate.created"
    CANDIDATE_REVISED = "candidate.revised"
    CANDIDATE_DEDUPLICATED = "candidate.deduplicated"
    CANDIDATE_CONFLICT_DETECTED = "candidate.conflict_detected"
    CANDIDATE_REVIEW_STARTED = "candidate.review_started"
    CANDIDATE_REJECTED = "candidate.rejected"
    CANDIDATE_QUARANTINED = "candidate.quarantined"
    CANDIDATE_QUARANTINE_RESOLVED = "candidate.quarantine_resolved"
    LIFECYCLE_TRANSITION_DENIED = "lifecycle.transition_denied"


class IngestDisposition(str, Enum):
    CREATED = "created"
    REVISED = "revised"
    NOOP = "noop"


class CandidateRevisionRecord(StrictFrozenModel):
    candidate_id: Identifier
    revision: int = Field(ge=1)
    previous_revision: int | None = Field(default=None, ge=1)
    previous_content_hash: Digest | None = None
    candidate_payload: LearningCandidate
    state: CandidateState
    content_hash: Digest
    transition_id: Identifier | None = None
    ingest_id: Identifier | None = None
    created_at: datetime = Field(default_factory=utc_now)
    record_hash: Digest

    _normalize_created = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def _revision_contract(self) -> CandidateRevisionRecord:
        if self.candidate_payload.candidate_id != self.candidate_id:
            raise ValueError("candidate payload identity does not match revision")
        if self.candidate_payload.revision != self.revision:
            raise ValueError("candidate payload revision does not match revision")
        if self.candidate_payload.state is not self.state:
            raise ValueError("candidate payload state does not match revision")
        if self.candidate_payload.content_hash != self.content_hash:
            raise ValueError("candidate payload hash does not match revision")
        if self.revision == 1:
            if self.previous_revision is not None or self.previous_content_hash:
                raise ValueError("revision 1 cannot have a parent")
            if self.ingest_id is None or self.transition_id is not None:
                raise ValueError("revision 1 requires ingest_id only")
        else:
            if self.previous_revision != self.revision - 1:
                raise ValueError("revision parent must be immediately previous")
            if self.previous_content_hash is None:
                raise ValueError("later revision requires previous_content_hash")
            if (self.transition_id is None) == (self.ingest_id is None):
                raise ValueError("later revision requires transition_id or ingest_id")
        if self.record_hash != self.recompute_hash():
            raise ValueError("record_hash does not match candidate revision")
        return self

    def semantic_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            exclude={"record_hash"},
        )

    def recompute_hash(self) -> str:
        return _digest(self.semantic_payload())


class CandidateHead(StrictFrozenModel):
    candidate_id: Identifier
    duplicate_signature: Digest
    revision: int = Field(ge=1)
    content_hash: Digest
    state: CandidateState
    project: Identifier
    scope: CandidateScope
    candidate_type: CandidateType
    proposed_destination: ProposedDestination
    updated_at: datetime

    _normalize_updated = field_validator("updated_at")(_utc)


class PersistedDuplicateLink(StrictFrozenModel):
    link_id: Identifier
    duplicate_signature: Digest
    candidate_id: Identifier
    extraction_run_id: Identifier
    source_evaluation_ids: tuple[Identifier, ...]
    reason: DuplicateReason
    created_at: datetime = Field(default_factory=utc_now)
    link_hash: Digest

    _normalize_created = field_validator("created_at")(_utc)

    @field_validator("source_evaluation_ids")
    @classmethod
    def _sort_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    def semantic_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"link_hash"})

    def recompute_hash(self) -> str:
        return _digest(self.semantic_payload())

    @model_validator(mode="after")
    def _hash_matches(self) -> PersistedDuplicateLink:
        if self.link_hash != self.recompute_hash():
            raise ValueError("duplicate link hash does not match payload")
        return self


class PersistedConflictLink(StrictFrozenModel):
    conflict_id: Identifier
    conflict_type: ConflictType
    conflict_signature: Digest
    candidate_ids: tuple[Identifier, Identifier]
    candidate_duplicate_signatures: tuple[Digest, Digest]
    priority: ConflictPriority
    preferred_candidate_id: Identifier | None = None
    reason: ShortText
    is_open: bool = True
    extraction_run_id: Identifier
    created_at: datetime = Field(default_factory=utc_now)
    conflict_hash: Digest

    _normalize_created = field_validator("created_at")(_utc)

    @field_validator("candidate_ids", "candidate_duplicate_signatures")
    @classmethod
    def _sort_pair(cls, values: tuple[str, str]) -> tuple[str, str]:
        if values[0] == values[1]:
            raise ValueError("conflict requires two distinct references")
        ordered = sorted(values)
        return (ordered[0], ordered[1])

    @model_validator(mode="after")
    def _conflict_contract(self) -> PersistedConflictLink:
        if self.priority is ConflictPriority.USER_CORRECTION:
            if self.preferred_candidate_id not in self.candidate_ids:
                raise ValueError("preferred correction must reference one candidate")
        elif self.preferred_candidate_id is not None:
            raise ValueError("preferred candidate requires correction priority")
        expected_signature = _digest(
            {
                "type": self.conflict_type.value,
                "candidate_duplicate_signatures": list(
                    self.candidate_duplicate_signatures
                ),
            }
        )
        if self.conflict_signature != expected_signature:
            raise ValueError("conflict signature does not match candidate signatures")
        if self.conflict_hash != self.recompute_hash():
            raise ValueError("conflict hash does not match payload")
        return self

    def semantic_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"conflict_hash"})

    def recompute_hash(self) -> str:
        return _digest(self.semantic_payload())


class AuditEvent(StrictFrozenModel):
    event_id: Identifier = Field(default_factory=lambda: f"event_{uuid.uuid4().hex}")
    sequence: int = Field(ge=1)
    event_type: AuditEventType
    candidate_id: Identifier | None = None
    revision: int | None = Field(default=None, ge=1)
    correlation_id: Identifier
    actor_type: ActorType | None = None
    actor_id: Identifier | None = None
    reason_code: Identifier
    reference_ids: tuple[Identifier, ...] = ()
    timestamp: datetime = Field(default_factory=utc_now)
    event_hash: Digest

    _normalize_timestamp = field_validator("timestamp")(_utc)

    @field_validator("reference_ids")
    @classmethod
    def _sort_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _actor_and_hash(self) -> AuditEvent:
        if (self.actor_type is None) != (self.actor_id is None):
            raise ValueError("audit actor type and id must appear together")
        if self.event_hash != self.recompute_hash():
            raise ValueError("event_hash does not match event payload")
        return self

    def semantic_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"event_hash"})

    def recompute_hash(self) -> str:
        return _digest(self.semantic_payload())


class CandidateIngestOutcome(StrictFrozenModel):
    extraction_candidate_id: Identifier
    candidate_id: Identifier
    revision: int = Field(ge=1)
    disposition: IngestDisposition


class IngestOutcome(StrictFrozenModel):
    run_id: Identifier
    run_hash: Digest
    candidates: tuple[CandidateIngestOutcome, ...]
    idempotent: bool = False


class StoredTransition(StrictFrozenModel):
    transition: TransitionRecord
    revision: CandidateRevisionRecord


__all__ = [
    "AuditEvent",
    "AuditEventType",
    "CandidateHead",
    "CandidateIngestOutcome",
    "CandidateRevisionRecord",
    "IngestDisposition",
    "IngestOutcome",
    "PersistedConflictLink",
    "PersistedDuplicateLink",
    "StoredTransition",
]
