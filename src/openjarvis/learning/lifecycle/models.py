"""Strict records for transactional candidate review transitions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.candidates.models import (
    CandidateState,
    Digest,
    Identifier,
    QuarantineReason,
    ShortText,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ActorType(str, Enum):
    USER = "user"
    SYSTEM_POLICY = "system_policy"
    DETERMINISTIC_TEST = "deterministic_test"


class QuarantineResolution(StrictFrozenModel):
    resolution_id: Identifier
    quarantine_reason: QuarantineReason
    evidence_digest: Digest
    summary: ShortText


class TransitionRequest(StrictFrozenModel):
    candidate_id: Identifier
    expected_revision: int = Field(ge=1)
    target_state: CandidateState
    actor_type: ActorType
    actor_id: Identifier
    reason: ShortText
    reason_code: Identifier
    correlation_id: Identifier
    idempotency_key: Identifier
    evidence_reference_ids: tuple[Identifier, ...] = ()
    skill_lifecycle_record_id: Identifier | None = None
    quarantine_resolution_records: tuple[QuarantineResolution, ...] = ()
    quarantine_reasons: tuple[QuarantineReason, ...] = ()

    @field_validator("quarantine_resolution_records")
    @classmethod
    def _sort_resolutions(
        cls,
        values: tuple[QuarantineResolution, ...],
    ) -> tuple[QuarantineResolution, ...]:
        reasons = [value.quarantine_reason for value in values]
        if len(reasons) != len(set(reasons)):
            raise ValueError("one resolution record is allowed per quarantine reason")
        return tuple(sorted(values, key=lambda value: value.quarantine_reason.value))

    @field_validator("evidence_reference_ids")
    @classmethod
    def _sort_evidence_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("quarantine_reasons")
    @classmethod
    def _sort_reasons(
        cls,
        values: tuple[QuarantineReason, ...],
    ) -> tuple[QuarantineReason, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @model_validator(mode="after")
    def _target_contract(self) -> TransitionRequest:
        if self.target_state is CandidateState.QUARANTINED:
            if not self.quarantine_reasons:
                raise ValueError("quarantine transition requires quarantine reasons")
        elif self.quarantine_reasons:
            raise ValueError("quarantine reasons require quarantined target state")
        return self

    def semantic_digest(self) -> str:
        payload = self.model_dump(mode="json")
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class TransitionRecord(StrictFrozenModel):
    transition_id: Identifier = Field(
        default_factory=lambda: f"transition_{uuid.uuid4().hex}"
    )
    candidate_id: Identifier
    expected_revision: int = Field(ge=1)
    source_revision: int = Field(ge=1)
    target_revision: int = Field(ge=2)
    from_state: CandidateState
    to_state: CandidateState
    actor_type: ActorType
    actor_id: Identifier
    reason: ShortText
    reason_code: Identifier
    correlation_id: Identifier
    idempotency_key: Identifier
    evidence_reference_ids: tuple[Identifier, ...] = ()
    skill_lifecycle_record_id: Identifier | None = None
    quarantine_resolution_ids: tuple[Identifier, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)
    transition_hash: Digest

    _normalize_created = field_validator("created_at")(_utc)

    @field_validator("evidence_reference_ids", "quarantine_resolution_ids")
    @classmethod
    def _sort_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _record_contract(self) -> TransitionRecord:
        if self.expected_revision != self.source_revision:
            raise ValueError("expected_revision must equal source_revision")
        if self.target_revision != self.source_revision + 1:
            raise ValueError("target_revision must be source_revision + 1")
        if self.transition_hash != self.recompute_hash():
            raise ValueError("transition_hash does not match transition payload")
        return self

    def semantic_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            exclude={"transition_hash"},
        )

    def recompute_hash(self) -> str:
        serialized = json.dumps(
            self.semantic_payload(), separators=(",", ":"), sort_keys=True
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class TransitionOutcome(StrictFrozenModel):
    transition: TransitionRecord
    candidate_id: Identifier
    revision: int = Field(ge=2)
    content_hash: Digest
    idempotent: bool = False


__all__ = [
    "ActorType",
    "QuarantineResolution",
    "TransitionOutcome",
    "TransitionRecord",
    "TransitionRequest",
]
