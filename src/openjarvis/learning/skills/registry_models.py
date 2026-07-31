"""Immutable records exposed by the persistent skill registry."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.evaluation.models import Digest, Identifier
from openjarvis.learning.lifecycle.models import ActorType
from openjarvis.learning.skills.manifest import (
    SemanticVersion,
    SkillIdentifier,
    SkillLifecycleStatus,
    SkillManifest,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RegistryDisposition(str, Enum):
    CREATED = "created"
    REPLAYED = "replayed"


class SkillAuditEventType(str, Enum):
    MANIFEST_CREATED = "skill.manifest_created"
    VERSION_REGISTERED = "skill.version_registered"
    TEST_STARTED = "skill.test_started"
    TEST_PASSED = "skill.test_passed"
    TEST_FAILED = "skill.test_failed"
    VERIFICATION_FAILED = "skill.verification_failed"
    VERIFIED = "skill.verified"
    PROMOTION_REQUESTED = "skill.promotion_requested"
    PROMOTION_DENIED = "skill.promotion_denied"
    PROMOTED = "skill.promoted"
    ACTIVATION_REQUESTED = "skill.activation_requested"
    ACTIVATED = "skill.activated"
    EXECUTION_STARTED = "skill.execution_started"
    EXECUTION_COMPLETED = "skill.execution_completed"
    EXECUTION_FAILED = "skill.execution_failed"
    DEPRECATED = "skill.deprecated"
    ROLLBACK_REQUESTED = "skill.rollback_requested"
    ROLLED_BACK = "skill.rolled_back"
    IMPORT_QUARANTINED = "skill.import_quarantined"
    CONFLICT_RESOLVED = "conflict.resolved"


class SkillVersionRecord(StrictFrozenModel):
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    registry_revision: int = Field(ge=1)
    manifest_hash: Digest
    candidate_id: Identifier
    candidate_revision: int = Field(ge=1)
    supersedes_version: SemanticVersion | None = None
    created_at: datetime
    record_hash: Digest

    _normalise_created_at = field_validator("created_at")(_utc)

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def recompute_hash(self) -> str:
        return _digest(self.semantic_payload())

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        if self.record_hash != self.recompute_hash():
            raise ValueError("skill version record_hash mismatch")
        return self


class SkillVersionHead(StrictFrozenModel):
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    lifecycle_state: SkillLifecycleStatus
    state_revision: int = Field(ge=1)
    manifest_hash: Digest
    candidate_id: Identifier
    candidate_revision: int = Field(ge=1)
    updated_at: datetime

    _normalise_updated_at = field_validator("updated_at")(_utc)


class SkillRegistrationOutcome(StrictFrozenModel):
    manifest: SkillManifest
    version: SkillVersionRecord
    head: SkillVersionHead
    disposition: RegistryDisposition


class SkillAuditEvent(StrictFrozenModel):
    event_id: Identifier
    sequence: int = Field(ge=1)
    event_type: SkillAuditEventType
    skill_id: SkillIdentifier | None = None
    semantic_version: SemanticVersion | None = None
    candidate_id: Identifier | None = None
    candidate_revision: int | None = Field(default=None, ge=1)
    task_id: Identifier | None = None
    session_id: Identifier | None = None
    correlation_id: Identifier
    actor_type: ActorType | None = None
    actor_id: Identifier | None = None
    reason_code: Identifier
    reference_ids: tuple[Identifier, ...] = ()
    created_at: datetime
    event_hash: Digest

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("reference_ids")
    @classmethod
    def _normalise_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _contract(self) -> Self:
        if (self.skill_id is None) != (self.semantic_version is None):
            raise ValueError("skill identity and version must appear together")
        if (self.actor_type is None) != (self.actor_id is None):
            raise ValueError("audit actor fields must appear together")
        if self.event_hash != self.recompute_hash():
            raise ValueError("skill event_hash mismatch")
        return self

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"event_hash"})

    def recompute_hash(self) -> str:
        return _digest(self.semantic_payload())


__all__ = [
    "RegistryDisposition",
    "SkillAuditEvent",
    "SkillAuditEventType",
    "SkillRegistrationOutcome",
    "SkillVersionHead",
    "SkillVersionRecord",
]
