"""Explicit promotion, activation, deprecation and rollback authority."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.candidates.models import CandidateState
from openjarvis.learning.evaluation.models import Digest, Identifier
from openjarvis.learning.lifecycle.models import ActorType, TransitionRequest
from openjarvis.learning.skills.manifest import (
    SemanticVersion,
    SkillIdentifier,
    SkillManifest,
)
from openjarvis.learning.skills.registry import (
    SkillRegistry,
    SkillRegistryError,
    _digest,
    _iso,
    _now,
    _validate_identifier,
)
from openjarvis.learning.skills.registry_models import (
    SkillAuditEventType,
    SkillVersionHead,
)
from openjarvis.learning.skills.verification import (
    SkillVerificationRecord,
    VerificationStatus,
)
from openjarvis.learning.store.repository import (
    ExpectedRevisionError,
    LearningIntegrityError,
    LearningRecordNotFoundError,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PromotionDecision(str, Enum):
    PENDING = "pending"
    ALLOW_ONCE = "allow_once"
    DENY = "deny"


class ActivationDecision(str, Enum):
    ALLOW_ONCE = "allow_once"


class ActivationKind(str, Enum):
    ACTIVATE = "activate"
    ROLLBACK = "rollback"


class _HealthcheckPayload(StrictFrozenModel):
    healthcheck_id: Identifier
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    manifest_hash: Digest
    passed: bool
    evidence_reference_ids: tuple[Identifier, ...]
    evidence_digests: tuple[Digest, ...]
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("evidence_reference_ids", "evidence_digests")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("healthcheck requires evidence")
        return values


class SkillHealthcheckResult(_HealthcheckPayload):
    healthcheck_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillHealthcheckResult:
        payload = _HealthcheckPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "healthcheck_hash": _digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"healthcheck_hash"})
        if self.healthcheck_hash != _digest(payload):
            raise ValueError("healthcheck_hash mismatch")
        return self


HealthcheckRunner = Callable[[SkillManifest], SkillHealthcheckResult]


class _PromotionPayload(StrictFrozenModel):
    promotion_id: Identifier
    request_promotion_id: Identifier | None = None
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    candidate_id: Identifier
    candidate_revision: int = Field(ge=1)
    manifest_hash: Digest
    verification_id: Identifier
    decision: PromotionDecision
    activation_intended: bool
    actor_type: ActorType
    actor_id: Identifier
    reason_code: Identifier
    correlation_id: Identifier
    evidence_reference_ids: tuple[Identifier, ...]
    evidence_digests: tuple[Digest, ...]
    idempotency_key: Identifier
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("evidence_reference_ids", "evidence_digests")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("promotion requires evidence")
        return values

    @model_validator(mode="after")
    def _decision_contract(self) -> Self:
        if self.decision is PromotionDecision.PENDING:
            if self.request_promotion_id is not None:
                raise ValueError("promotion request cannot reference another request")
        elif self.request_promotion_id is None:
            raise ValueError("promotion decision must reference its request")
        return self


class SkillPromotionRecord(_PromotionPayload):
    record_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillPromotionRecord:
        payload = _PromotionPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "record_hash": _digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"record_hash"})
        if self.record_hash != _digest(payload):
            raise ValueError("promotion record_hash mismatch")
        return self


class _ActivationPayload(StrictFrozenModel):
    activation_id: Identifier
    kind: ActivationKind
    scope_key: Identifier
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    previous_skill_id: SkillIdentifier | None = None
    previous_semantic_version: SemanticVersion | None = None
    expected_scope_revision: int = Field(ge=0)
    target_scope_revision: int = Field(ge=1)
    manifest_hash: Digest
    decision: ActivationDecision
    actor_type: ActorType
    actor_id: Identifier
    reason_code: Identifier
    correlation_id: Identifier
    healthcheck: SkillHealthcheckResult
    evidence_reference_ids: tuple[Identifier, ...]
    idempotency_key: Identifier
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("evidence_reference_ids")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("activation requires evidence")
        return values

    @model_validator(mode="after")
    def _contract(self) -> Self:
        if (self.previous_skill_id is None) != (self.previous_semantic_version is None):
            raise ValueError("previous skill identity must be complete")
        if self.target_scope_revision != self.expected_scope_revision + 1:
            raise ValueError("activation scope revision must advance exactly once")
        return self


class SkillActivationRecord(_ActivationPayload):
    record_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillActivationRecord:
        payload = _ActivationPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "record_hash": _digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"record_hash"})
        if self.record_hash != _digest(payload):
            raise ValueError("activation record_hash mismatch")
        return self


class _DeprecationPayload(StrictFrozenModel):
    deprecation_id: Identifier
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    candidate_id: Identifier
    candidate_revision: int = Field(ge=1)
    expected_state_revision: int = Field(ge=1)
    target_state_revision: int = Field(ge=2)
    scope_key: Identifier | None = None
    expected_scope_revision: int | None = Field(default=None, ge=1)
    actor_type: ActorType
    actor_id: Identifier
    reason_code: Identifier
    correlation_id: Identifier
    evidence_reference_ids: tuple[Identifier, ...]
    idempotency_key: Identifier
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("evidence_reference_ids")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("deprecation requires evidence")
        return values

    @model_validator(mode="after")
    def _contract(self) -> Self:
        if self.target_state_revision != self.expected_state_revision + 1:
            raise ValueError("deprecation state revision must advance exactly once")
        if (self.scope_key is None) != (self.expected_scope_revision is None):
            raise ValueError("deprecation scope CAS fields must appear together")
        return self


class SkillDeprecationRecord(_DeprecationPayload):
    record_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillDeprecationRecord:
        payload = _DeprecationPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "record_hash": _digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"record_hash"})
        if self.record_hash != _digest(payload):
            raise ValueError("deprecation record_hash mismatch")
        return self


class _RollbackPayload(StrictFrozenModel):
    rollback_id: Identifier
    scope_key: Identifier
    from_skill_id: SkillIdentifier
    from_semantic_version: SemanticVersion
    target_skill_id: SkillIdentifier
    target_semantic_version: SemanticVersion
    expected_scope_revision: int = Field(ge=1)
    target_scope_revision: int = Field(ge=2)
    activation_id: Identifier
    actor_type: ActorType
    actor_id: Identifier
    reason_code: Identifier
    correlation_id: Identifier
    healthcheck: SkillHealthcheckResult
    evidence_reference_ids: tuple[Identifier, ...]
    idempotency_key: Identifier
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("evidence_reference_ids")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("rollback requires evidence")
        return values

    @model_validator(mode="after")
    def _contract(self) -> Self:
        if self.target_scope_revision != self.expected_scope_revision + 1:
            raise ValueError("rollback scope revision must advance exactly once")
        if (
            self.from_skill_id == self.target_skill_id
            and self.from_semantic_version == self.target_semantic_version
        ):
            raise ValueError("rollback target must differ from current version")
        return self


class SkillRollbackRecord(_RollbackPayload):
    record_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillRollbackRecord:
        payload = _RollbackPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "record_hash": _digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"record_hash"})
        if self.record_hash != _digest(payload):
            raise ValueError("rollback record_hash mismatch")
        return self


class PromotionOutcome(StrictFrozenModel):
    record: SkillPromotionRecord
    skill_head: SkillVersionHead
    candidate_revision: int = Field(ge=2)
    idempotent: bool = False


class ActivationOutcome(StrictFrozenModel):
    record: SkillActivationRecord
    skill_head: SkillVersionHead
    scope_revision: int = Field(ge=1)
    idempotent: bool = False


class RollbackOutcome(StrictFrozenModel):
    record: SkillRollbackRecord
    activation: SkillActivationRecord
    current_head: SkillVersionHead
    target_head: SkillVersionHead
    scope_revision: int = Field(ge=2)
    idempotent: bool = False


class SkillLifecycleService:
    """The sole mutation service for trusted skill lifecycle changes."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def request_promotion(
        self,
        *,
        skill_id: str,
        semantic_version: str,
        expected_candidate_revision: int,
        expected_state_revision: int,
        activation_intended: bool,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        evidence_reference_ids: tuple[str, ...],
        evidence_digests: tuple[str, ...],
        idempotency_key: str,
    ) -> PromotionOutcome:
        self._validate_mutation(
            actor_id,
            reason_code,
            correlation_id,
            idempotency_key,
            evidence_reference_ids,
        )
        if not evidence_digests:
            raise SkillRegistryError("promotion requires evidence digests")
        request_digest = _digest(
            {
                "operation": "skill.promotion.request",
                "skill_id": skill_id,
                "semantic_version": semantic_version,
                "expected_candidate_revision": expected_candidate_revision,
                "expected_state_revision": expected_state_revision,
                "activation_intended": activation_intended,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "reason_code": reason_code,
                "correlation_id": correlation_id,
                "evidence_reference_ids": sorted(evidence_reference_ids),
                "evidence_digests": sorted(evidence_digests),
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.promotion.request",
                request_digest=request_digest,
            )
            if replay is not None:
                return PromotionOutcome(
                    record=self._promotion(connection, replay["promotion_id"]),
                    skill_head=self.registry._head(
                        connection, skill_id, semantic_version
                    ),
                    candidate_revision=int(replay["candidate_revision"]),
                    idempotent=True,
                )
            head = self._expected_head(
                connection,
                skill_id,
                semantic_version,
                expected_candidate_revision,
                expected_state_revision,
                "verified",
            )
            verification = self._promotion_prerequisites(
                connection, head, activation_required=activation_intended
            )
            created_at = _now()
            record = SkillPromotionRecord.create(
                {
                    "promotion_id": f"promotion_request_{uuid.uuid4().hex}",
                    "skill_id": skill_id,
                    "semantic_version": semantic_version,
                    "candidate_id": head.candidate_id,
                    "candidate_revision": head.candidate_revision,
                    "manifest_hash": head.manifest_hash,
                    "verification_id": verification.verification_id,
                    "decision": PromotionDecision.PENDING,
                    "activation_intended": activation_intended,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "reason_code": reason_code,
                    "correlation_id": correlation_id,
                    "evidence_reference_ids": evidence_reference_ids,
                    "evidence_digests": evidence_digests,
                    "idempotency_key": idempotency_key,
                    "created_at": created_at,
                }
            )
            self._insert_promotion(connection, record)
            outcome = self.registry.learning._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=head.candidate_id,
                    expected_revision=head.candidate_revision,
                    target_state=CandidateState.PROMOTION_PENDING,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="Explicit skill promotion review requested.",
                    reason_code=reason_code,
                    correlation_id=correlation_id,
                    idempotency_key=self._child_key(idempotency_key, "candidate"),
                    evidence_reference_ids=evidence_reference_ids
                    + (verification.verification_id,),
                    skill_lifecycle_record_id=record.promotion_id,
                ),
                skill_lifecycle_authorized=True,
            )
            updated = self._cas_head(
                connection, head, "promotion_pending", outcome.revision
            )
            self.registry._append_event(
                connection,
                event_type=SkillAuditEventType.PROMOTION_REQUESTED,
                skill_id=skill_id,
                semantic_version=semantic_version,
                candidate_id=head.candidate_id,
                candidate_revision=outcome.revision,
                correlation_id=correlation_id,
                actor_type=actor_type,
                actor_id=actor_id,
                reason_code=reason_code,
                reference_ids=evidence_reference_ids + (record.promotion_id,),
                created_at=created_at,
            )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.promotion.request",
                request_digest=request_digest,
                references={
                    "promotion_id": record.promotion_id,
                    "candidate_revision": outcome.revision,
                },
            )
            return PromotionOutcome(
                record=record,
                skill_head=updated,
                candidate_revision=outcome.revision,
            )

    def decide_promotion(
        self,
        *,
        request_promotion_id: str,
        decision: PromotionDecision,
        expected_candidate_revision: int,
        expected_state_revision: int,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        evidence_reference_ids: tuple[str, ...],
        evidence_digests: tuple[str, ...],
        idempotency_key: str,
    ) -> PromotionOutcome:
        self._validate_mutation(
            actor_id,
            reason_code,
            correlation_id,
            idempotency_key,
            evidence_reference_ids,
        )
        if decision not in {PromotionDecision.ALLOW_ONCE, PromotionDecision.DENY}:
            raise SkillRegistryError("promotion requires allow-once or deny")
        if decision is PromotionDecision.ALLOW_ONCE and actor_type not in {
            ActorType.USER,
            ActorType.DETERMINISTIC_TEST,
        }:
            raise SkillRegistryError("promotion allow-once requires a local reviewer")
        if not evidence_digests:
            raise SkillRegistryError("promotion decision requires evidence digests")
        with self.registry.database.reader() as connection:
            pending = self._promotion(connection, request_promotion_id)
        request_digest = _digest(
            {
                "operation": "skill.promotion.decide",
                "request_promotion_id": request_promotion_id,
                "decision": decision.value,
                "expected_candidate_revision": expected_candidate_revision,
                "expected_state_revision": expected_state_revision,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "reason_code": reason_code,
                "correlation_id": correlation_id,
                "evidence_reference_ids": sorted(evidence_reference_ids),
                "evidence_digests": sorted(evidence_digests),
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.promotion.decide",
                request_digest=request_digest,
            )
            if replay is not None:
                return PromotionOutcome(
                    record=self._promotion(connection, replay["promotion_id"]),
                    skill_head=self.registry._head(
                        connection, pending.skill_id, pending.semantic_version
                    ),
                    candidate_revision=int(replay["candidate_revision"]),
                    idempotent=True,
                )
            pending = self._promotion(connection, request_promotion_id)
            if pending.decision is not PromotionDecision.PENDING:
                raise SkillRegistryError("referenced record is not a promotion request")
            head = self._expected_head(
                connection,
                pending.skill_id,
                pending.semantic_version,
                expected_candidate_revision,
                expected_state_revision,
                "promotion_pending",
            )
            if decision is PromotionDecision.ALLOW_ONCE:
                self._promotion_prerequisites(
                    connection,
                    head,
                    activation_required=pending.activation_intended,
                )
            created_at = _now()
            record = SkillPromotionRecord.create(
                {
                    "promotion_id": f"promotion_decision_{uuid.uuid4().hex}",
                    "request_promotion_id": pending.promotion_id,
                    "skill_id": head.skill_id,
                    "semantic_version": head.semantic_version,
                    "candidate_id": head.candidate_id,
                    "candidate_revision": head.candidate_revision,
                    "manifest_hash": head.manifest_hash,
                    "verification_id": pending.verification_id,
                    "decision": decision,
                    "activation_intended": pending.activation_intended,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "reason_code": reason_code,
                    "correlation_id": correlation_id,
                    "evidence_reference_ids": evidence_reference_ids,
                    "evidence_digests": evidence_digests,
                    "idempotency_key": idempotency_key,
                    "created_at": created_at,
                }
            )
            self._insert_promotion(connection, record)
            target = (
                CandidateState.PROMOTED
                if decision is PromotionDecision.ALLOW_ONCE
                else CandidateState.REJECTED
            )
            outcome = self.registry.learning._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=head.candidate_id,
                    expected_revision=head.candidate_revision,
                    target_state=target,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="Explicit skill promotion review completed.",
                    reason_code=reason_code,
                    correlation_id=correlation_id,
                    idempotency_key=self._child_key(idempotency_key, "candidate"),
                    evidence_reference_ids=evidence_reference_ids
                    + (pending.promotion_id,),
                    skill_lifecycle_record_id=record.promotion_id,
                ),
                skill_lifecycle_authorized=True,
            )
            updated = self._cas_head(connection, head, target.value, outcome.revision)
            self.registry._append_event(
                connection,
                event_type=(
                    SkillAuditEventType.PROMOTED
                    if target is CandidateState.PROMOTED
                    else SkillAuditEventType.PROMOTION_DENIED
                ),
                skill_id=head.skill_id,
                semantic_version=head.semantic_version,
                candidate_id=head.candidate_id,
                candidate_revision=outcome.revision,
                correlation_id=correlation_id,
                actor_type=actor_type,
                actor_id=actor_id,
                reason_code=reason_code,
                reference_ids=evidence_reference_ids + (record.promotion_id,),
                created_at=created_at,
            )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.promotion.decide",
                request_digest=request_digest,
                references={
                    "promotion_id": record.promotion_id,
                    "candidate_revision": outcome.revision,
                },
            )
            return PromotionOutcome(
                record=record,
                skill_head=updated,
                candidate_revision=outcome.revision,
            )

    def activate(
        self,
        *,
        skill_id: str,
        semantic_version: str,
        expected_candidate_revision: int,
        expected_state_revision: int,
        scope_key: str,
        expected_scope_revision: int,
        expected_active_skill_id: str | None,
        expected_active_semantic_version: str | None,
        decision: ActivationDecision,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        evidence_reference_ids: tuple[str, ...],
        idempotency_key: str,
        healthcheck_runner: HealthcheckRunner,
    ) -> ActivationOutcome:
        self._validate_explicit_activation(
            decision,
            actor_type,
            actor_id,
            reason_code,
            correlation_id,
            idempotency_key,
            scope_key,
            evidence_reference_ids,
        )
        with self.registry.database.reader() as connection:
            manifest = self.registry._manifest(connection, skill_id, semantic_version)
        healthcheck = healthcheck_runner(manifest)
        self._validate_healthcheck(healthcheck, manifest)
        request_digest = _digest(
            {
                "operation": "skill.activate",
                "skill_id": skill_id,
                "semantic_version": semantic_version,
                "expected_candidate_revision": expected_candidate_revision,
                "expected_state_revision": expected_state_revision,
                "scope_key": scope_key,
                "expected_scope_revision": expected_scope_revision,
                "expected_active_skill_id": expected_active_skill_id,
                "expected_active_semantic_version": expected_active_semantic_version,
                "decision": decision.value,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "reason_code": reason_code,
                "correlation_id": correlation_id,
                "evidence_reference_ids": sorted(evidence_reference_ids),
                "healthcheck_hash": healthcheck.healthcheck_hash,
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.activate",
                request_digest=request_digest,
            )
            if replay is not None:
                record = self._activation(connection, replay["activation_id"])
                return ActivationOutcome(
                    record=record,
                    skill_head=self.registry._head(
                        connection, record.skill_id, record.semantic_version
                    ),
                    scope_revision=record.target_scope_revision,
                    idempotent=True,
                )
            head = self._expected_head(
                connection,
                skill_id,
                semantic_version,
                expected_candidate_revision,
                expected_state_revision,
                "promoted",
            )
            self._promotion_prerequisites(connection, head, activation_required=True)
            scope = self._expected_scope(
                connection,
                scope_key,
                expected_scope_revision,
                expected_active_skill_id,
                expected_active_semantic_version,
            )
            if scope is not None and (
                scope["active_skill_id"] == skill_id
                and scope["active_semantic_version"] == semantic_version
            ):
                raise SkillRegistryError("skill version is already selected")
            created_at = _now()
            record = SkillActivationRecord.create(
                {
                    "activation_id": f"activation_{uuid.uuid4().hex}",
                    "kind": ActivationKind.ACTIVATE,
                    "scope_key": scope_key,
                    "skill_id": skill_id,
                    "semantic_version": semantic_version,
                    "previous_skill_id": (
                        scope["active_skill_id"] if scope is not None else None
                    ),
                    "previous_semantic_version": (
                        scope["active_semantic_version"] if scope is not None else None
                    ),
                    "expected_scope_revision": expected_scope_revision,
                    "target_scope_revision": expected_scope_revision + 1,
                    "manifest_hash": head.manifest_hash,
                    "decision": decision,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "reason_code": reason_code,
                    "correlation_id": correlation_id,
                    "healthcheck": healthcheck,
                    "evidence_reference_ids": evidence_reference_ids
                    + (healthcheck.healthcheck_id,),
                    "idempotency_key": idempotency_key,
                    "created_at": created_at,
                }
            )
            self._insert_activation(connection, record)
            if scope is not None:
                previous = self.registry._head(
                    connection,
                    scope["active_skill_id"],
                    scope["active_semantic_version"],
                )
                if previous.lifecycle_state.value == "active":
                    self._deprecate_in_transaction(
                        connection,
                        previous,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        reason_code="superseded_by_activation",
                        correlation_id=correlation_id,
                        evidence_reference_ids=(record.activation_id,),
                        idempotency_key=self._child_key(idempotency_key, "supersede"),
                    )
            outcome = self.registry.learning._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=head.candidate_id,
                    expected_revision=head.candidate_revision,
                    target_state=CandidateState.ACTIVE,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="Explicit activation healthcheck passed.",
                    reason_code=reason_code,
                    correlation_id=correlation_id,
                    idempotency_key=self._child_key(idempotency_key, "candidate"),
                    evidence_reference_ids=evidence_reference_ids
                    + (record.activation_id, healthcheck.healthcheck_id),
                    skill_lifecycle_record_id=record.activation_id,
                ),
                skill_lifecycle_authorized=True,
            )
            updated = self._cas_head(connection, head, "active", outcome.revision)
            self._write_scope(connection, scope, record)
            for event_type in (
                SkillAuditEventType.ACTIVATION_REQUESTED,
                SkillAuditEventType.ACTIVATED,
            ):
                self.registry._append_event(
                    connection,
                    event_type=event_type,
                    skill_id=skill_id,
                    semantic_version=semantic_version,
                    candidate_id=head.candidate_id,
                    candidate_revision=outcome.revision,
                    correlation_id=correlation_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason_code=reason_code,
                    reference_ids=evidence_reference_ids
                    + (record.activation_id, healthcheck.healthcheck_id),
                    created_at=created_at,
                )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.activate",
                request_digest=request_digest,
                references={"activation_id": record.activation_id},
            )
            return ActivationOutcome(
                record=record,
                skill_head=updated,
                scope_revision=record.target_scope_revision,
            )

    def deprecate(
        self,
        *,
        skill_id: str,
        semantic_version: str,
        expected_candidate_revision: int,
        expected_state_revision: int,
        scope_key: str | None,
        expected_scope_revision: int | None,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        evidence_reference_ids: tuple[str, ...],
        idempotency_key: str,
    ) -> SkillDeprecationRecord:
        self._validate_mutation(
            actor_id,
            reason_code,
            correlation_id,
            idempotency_key,
            evidence_reference_ids,
        )
        request_digest = _digest(
            {
                "operation": "skill.deprecate",
                "skill_id": skill_id,
                "semantic_version": semantic_version,
                "expected_candidate_revision": expected_candidate_revision,
                "expected_state_revision": expected_state_revision,
                "scope_key": scope_key,
                "expected_scope_revision": expected_scope_revision,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "reason_code": reason_code,
                "correlation_id": correlation_id,
                "evidence_reference_ids": sorted(evidence_reference_ids),
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.deprecate",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._deprecation(connection, replay["deprecation_id"])
            head = self.registry._head(connection, skill_id, semantic_version)
            if (
                head.candidate_revision != expected_candidate_revision
                or head.state_revision != expected_state_revision
            ):
                raise ExpectedRevisionError("skill revision changed")
            if head.lifecycle_state.value not in {"active", "promoted"}:
                raise SkillRegistryError("only active or promoted skills deprecate")
            scope = None
            if head.lifecycle_state.value == "active":
                if scope_key is None or expected_scope_revision is None:
                    raise SkillRegistryError("active deprecation requires scope CAS")
                scope = self._expected_scope(
                    connection,
                    scope_key,
                    expected_scope_revision,
                    skill_id,
                    semantic_version,
                )
            elif scope_key is not None or expected_scope_revision is not None:
                raise SkillRegistryError("inactive deprecation has no scope CAS")
            record, _ = self._deprecate_in_transaction(
                connection,
                head,
                actor_type=actor_type,
                actor_id=actor_id,
                reason_code=reason_code,
                correlation_id=correlation_id,
                evidence_reference_ids=evidence_reference_ids,
                idempotency_key=idempotency_key,
                scope_key=scope_key,
                expected_scope_revision=expected_scope_revision,
            )
            if scope is not None:
                cursor = connection.execute(
                    """
                    UPDATE skill_scope_heads SET scope_revision = ?, updated_at = ?
                    WHERE scope_key = ? AND scope_revision = ?
                      AND active_skill_id = ? AND active_semantic_version = ?
                    """,
                    (
                        expected_scope_revision + 1,
                        _iso(_now()),
                        scope_key,
                        expected_scope_revision,
                        skill_id,
                        semantic_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExpectedRevisionError("skill scope CAS failed")
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.deprecate",
                request_digest=request_digest,
                references={"deprecation_id": record.deprecation_id},
            )
            return record

    def rollback(
        self,
        *,
        scope_key: str,
        expected_scope_revision: int,
        current_skill_id: str,
        current_semantic_version: str,
        target_skill_id: str,
        target_semantic_version: str,
        decision: ActivationDecision,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        evidence_reference_ids: tuple[str, ...],
        idempotency_key: str,
        healthcheck_runner: HealthcheckRunner,
    ) -> RollbackOutcome:
        self._validate_explicit_activation(
            decision,
            actor_type,
            actor_id,
            reason_code,
            correlation_id,
            idempotency_key,
            scope_key,
            evidence_reference_ids,
        )
        if target_skill_id != current_skill_id:
            raise SkillRegistryError("rollback target must retain the stable skill ID")
        with self.registry.database.reader() as connection:
            target_manifest = self.registry._manifest(
                connection, target_skill_id, target_semantic_version
            )
        healthcheck = healthcheck_runner(target_manifest)
        self._validate_healthcheck(healthcheck, target_manifest)
        request_digest = _digest(
            {
                "operation": "skill.rollback",
                "scope_key": scope_key,
                "expected_scope_revision": expected_scope_revision,
                "current_skill_id": current_skill_id,
                "current_semantic_version": current_semantic_version,
                "target_skill_id": target_skill_id,
                "target_semantic_version": target_semantic_version,
                "decision": decision.value,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "reason_code": reason_code,
                "correlation_id": correlation_id,
                "evidence_reference_ids": sorted(evidence_reference_ids),
                "healthcheck_hash": healthcheck.healthcheck_hash,
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.rollback",
                request_digest=request_digest,
            )
            if replay is not None:
                record = self._rollback(connection, replay["rollback_id"])
                activation = self._activation(connection, record.activation_id)
                return RollbackOutcome(
                    record=record,
                    activation=activation,
                    current_head=self.registry._head(
                        connection, current_skill_id, current_semantic_version
                    ),
                    target_head=self.registry._head(
                        connection, target_skill_id, target_semantic_version
                    ),
                    scope_revision=record.target_scope_revision,
                    idempotent=True,
                )
            scope = self._expected_scope(
                connection,
                scope_key,
                expected_scope_revision,
                current_skill_id,
                current_semantic_version,
            )
            if scope is None:
                raise SkillRegistryError("rollback requires an active scope")
            current = self.registry._head(
                connection, current_skill_id, current_semantic_version
            )
            target = self.registry._head(
                connection, target_skill_id, target_semantic_version
            )
            if current.lifecycle_state.value != "active":
                raise SkillRegistryError("rollback source is not active")
            if target.lifecycle_state.value not in {"deprecated", "promoted"}:
                raise SkillRegistryError("rollback target is not eligible")
            self._promotion_prerequisites(connection, target, activation_required=True)
            if current.candidate_id == target.candidate_id:
                raise SkillRegistryError(
                    "rollback versions require distinct candidates"
                )
            created_at = _now()
            activation = SkillActivationRecord.create(
                {
                    "activation_id": f"activation_rollback_{uuid.uuid4().hex}",
                    "kind": ActivationKind.ROLLBACK,
                    "scope_key": scope_key,
                    "skill_id": target_skill_id,
                    "semantic_version": target_semantic_version,
                    "previous_skill_id": current_skill_id,
                    "previous_semantic_version": current_semantic_version,
                    "expected_scope_revision": expected_scope_revision,
                    "target_scope_revision": expected_scope_revision + 1,
                    "manifest_hash": target.manifest_hash,
                    "decision": decision,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "reason_code": reason_code,
                    "correlation_id": correlation_id,
                    "healthcheck": healthcheck,
                    "evidence_reference_ids": evidence_reference_ids
                    + (healthcheck.healthcheck_id,),
                    "idempotency_key": self._child_key(idempotency_key, "activation"),
                    "created_at": created_at,
                }
            )
            self._insert_activation(connection, activation)
            record = SkillRollbackRecord.create(
                {
                    "rollback_id": f"rollback_{uuid.uuid4().hex}",
                    "scope_key": scope_key,
                    "from_skill_id": current_skill_id,
                    "from_semantic_version": current_semantic_version,
                    "target_skill_id": target_skill_id,
                    "target_semantic_version": target_semantic_version,
                    "expected_scope_revision": expected_scope_revision,
                    "target_scope_revision": expected_scope_revision + 1,
                    "activation_id": activation.activation_id,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "reason_code": reason_code,
                    "correlation_id": correlation_id,
                    "healthcheck": healthcheck,
                    "evidence_reference_ids": evidence_reference_ids
                    + (healthcheck.healthcheck_id,),
                    "idempotency_key": idempotency_key,
                    "created_at": created_at,
                }
            )
            self._insert_rollback(connection, record)
            current_outcome = self.registry.learning._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=current.candidate_id,
                    expected_revision=current.candidate_revision,
                    target_state=CandidateState.ROLLED_BACK,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="Explicit rollback replaced the active version.",
                    reason_code=reason_code,
                    correlation_id=correlation_id,
                    idempotency_key=self._child_key(idempotency_key, "source"),
                    evidence_reference_ids=evidence_reference_ids
                    + (record.rollback_id,),
                    skill_lifecycle_record_id=record.rollback_id,
                ),
                skill_lifecycle_authorized=True,
            )
            target_outcome = self.registry.learning._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=target.candidate_id,
                    expected_revision=target.candidate_revision,
                    target_state=CandidateState.ACTIVE,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="Explicit rollback target healthcheck passed.",
                    reason_code=reason_code,
                    correlation_id=correlation_id,
                    idempotency_key=self._child_key(idempotency_key, "target"),
                    evidence_reference_ids=evidence_reference_ids
                    + (record.rollback_id, healthcheck.healthcheck_id),
                    skill_lifecycle_record_id=record.rollback_id,
                ),
                skill_lifecycle_authorized=True,
            )
            current_updated = self._cas_head(
                connection, current, "rolled_back", current_outcome.revision
            )
            target_updated = self._cas_head(
                connection, target, "active", target_outcome.revision
            )
            self._write_scope(connection, scope, activation)
            for event_type in (
                SkillAuditEventType.ROLLBACK_REQUESTED,
                SkillAuditEventType.ROLLED_BACK,
            ):
                self.registry._append_event(
                    connection,
                    event_type=event_type,
                    skill_id=target_skill_id,
                    semantic_version=target_semantic_version,
                    candidate_id=target.candidate_id,
                    candidate_revision=target_outcome.revision,
                    correlation_id=correlation_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason_code=reason_code,
                    reference_ids=evidence_reference_ids
                    + (record.rollback_id, activation.activation_id),
                    created_at=created_at,
                )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.rollback",
                request_digest=request_digest,
                references={"rollback_id": record.rollback_id},
            )
            return RollbackOutcome(
                record=record,
                activation=activation,
                current_head=current_updated,
                target_head=target_updated,
                scope_revision=record.target_scope_revision,
            )

    def active_manifest(self, scope_key: str) -> SkillManifest:
        _validate_identifier(scope_key, "scope_key")
        with self.registry.database.reader() as connection:
            row = connection.execute(
                """
                SELECT active_skill_id, active_semantic_version,
                       active_manifest_hash
                FROM skill_scope_heads WHERE scope_key = ?
                """,
                (scope_key,),
            ).fetchone()
            if row is None:
                raise LearningRecordNotFoundError("active skill scope not found")
            head = self.registry._head(
                connection,
                row["active_skill_id"],
                row["active_semantic_version"],
            )
            if head.lifecycle_state.value != "active":
                raise LearningRecordNotFoundError("skill scope is deactivated")
            manifest = self.registry._manifest(
                connection, head.skill_id, head.semantic_version
            )
            if manifest.content_hash != row["active_manifest_hash"]:
                raise LearningIntegrityError("active manifest hash mismatch")
            return manifest

    def get_promotion(self, promotion_id: str) -> SkillPromotionRecord:
        with self.registry.database.reader() as connection:
            return self._promotion(connection, promotion_id)

    def get_activation(self, activation_id: str) -> SkillActivationRecord:
        with self.registry.database.reader() as connection:
            return self._activation(connection, activation_id)

    def get_deprecation(self, deprecation_id: str) -> SkillDeprecationRecord:
        with self.registry.database.reader() as connection:
            return self._deprecation(connection, deprecation_id)

    def get_rollback(self, rollback_id: str) -> SkillRollbackRecord:
        with self.registry.database.reader() as connection:
            return self._rollback(connection, rollback_id)

    def _promotion_prerequisites(
        self,
        connection: sqlite3.Connection,
        head: SkillVersionHead,
        *,
        activation_required: bool,
    ) -> SkillVerificationRecord:
        if self.registry.learning._has_open_conflict(connection, head.candidate_id):
            raise SkillRegistryError("open conflict prevents promotion or activation")
        candidate = self.registry.learning._get_head_candidate(
            connection, head.candidate_id
        )
        if candidate.quarantine_reasons:
            raise SkillRegistryError("quarantine prevents promotion or activation")
        manifest = self.registry._manifest(
            connection, head.skill_id, head.semantic_version
        )
        if manifest.content_hash != head.manifest_hash:
            raise LearningIntegrityError("skill head manifest hash mismatch")
        manifest.validate_tool_bindings(self.registry.tool_catalog)
        row = connection.execute(
            """
            SELECT payload_json FROM skill_verification_runs
            WHERE skill_id = ? AND semantic_version = ?
            ORDER BY completed_at DESC, run_id DESC LIMIT 1
            """,
            (head.skill_id, head.semantic_version),
        ).fetchone()
        if row is None:
            raise SkillRegistryError("promotion requires verification")
        try:
            verification = SkillVerificationRecord.model_validate_json(
                row["payload_json"]
            )
        except Exception as exc:
            raise LearningIntegrityError("verification integrity failure") from exc
        if (
            verification.status is not VerificationStatus.PASSED
            or verification.run.skill_id != head.skill_id
            or verification.run.semantic_version != head.semantic_version
            or verification.run.candidate_id != head.candidate_id
            or verification.run.manifest_hash != head.manifest_hash
        ):
            raise SkillRegistryError("verification does not match the skill head")
        if activation_required and not verification.activation_ready:
            raise SkillRegistryError("activation readiness evidence is incomplete")
        return verification

    @staticmethod
    def _validate_healthcheck(
        healthcheck: SkillHealthcheckResult, manifest: SkillManifest
    ) -> None:
        if (
            healthcheck.skill_id != manifest.skill_id
            or healthcheck.semantic_version != manifest.semantic_version
            or healthcheck.manifest_hash != manifest.content_hash
        ):
            raise SkillRegistryError("healthcheck is not bound to the target manifest")
        if not healthcheck.passed:
            raise SkillRegistryError("activation healthcheck failed")

    @staticmethod
    def _validate_mutation(
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        idempotency_key: str,
        evidence_reference_ids: tuple[str, ...],
    ) -> None:
        for value, field_name in (
            (actor_id, "actor_id"),
            (reason_code, "reason_code"),
            (correlation_id, "correlation_id"),
            (idempotency_key, "idempotency_key"),
        ):
            _validate_identifier(value, field_name)
        if not evidence_reference_ids:
            raise SkillRegistryError("lifecycle mutation requires evidence")
        for reference in evidence_reference_ids:
            _validate_identifier(reference, "evidence_reference_id")

    def _validate_explicit_activation(
        self,
        decision: ActivationDecision,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        idempotency_key: str,
        scope_key: str,
        evidence_reference_ids: tuple[str, ...],
    ) -> None:
        self._validate_mutation(
            actor_id,
            reason_code,
            correlation_id,
            idempotency_key,
            evidence_reference_ids,
        )
        _validate_identifier(scope_key, "scope_key")
        if decision is not ActivationDecision.ALLOW_ONCE:
            raise SkillRegistryError("activation requires allow-once")
        if actor_type not in {ActorType.USER, ActorType.DETERMINISTIC_TEST}:
            raise SkillRegistryError("activation requires a local reviewer")

    def _expected_head(
        self,
        connection: sqlite3.Connection,
        skill_id: str,
        semantic_version: str,
        expected_candidate_revision: int,
        expected_state_revision: int,
        expected_state: str,
    ) -> SkillVersionHead:
        head = self.registry._head(connection, skill_id, semantic_version)
        if (
            head.candidate_revision != expected_candidate_revision
            or head.state_revision != expected_state_revision
        ):
            raise ExpectedRevisionError("skill revision changed")
        if head.lifecycle_state.value != expected_state:
            raise SkillRegistryError(f"skill must be {expected_state}")
        return head

    @staticmethod
    def _expected_scope(
        connection: sqlite3.Connection,
        scope_key: str,
        expected_scope_revision: int,
        expected_active_skill_id: str | None,
        expected_active_semantic_version: str | None,
    ):
        if (expected_active_skill_id is None) != (
            expected_active_semantic_version is None
        ):
            raise SkillRegistryError("expected active identity must be complete")
        row = connection.execute(
            "SELECT * FROM skill_scope_heads WHERE scope_key = ?", (scope_key,)
        ).fetchone()
        if row is None:
            if expected_scope_revision != 0 or expected_active_skill_id is not None:
                raise ExpectedRevisionError("skill scope does not match expectation")
            return None
        if (
            int(row["scope_revision"]) != expected_scope_revision
            or row["active_skill_id"] != expected_active_skill_id
            or row["active_semantic_version"] != expected_active_semantic_version
        ):
            raise ExpectedRevisionError("skill scope CAS expectation changed")
        return row

    @staticmethod
    def _child_key(parent: str, purpose: str) -> str:
        return f"skill_{purpose}_{_digest({'parent': parent, 'purpose': purpose})[:32]}"

    @staticmethod
    def _cas_head(
        connection: sqlite3.Connection,
        head: SkillVersionHead,
        target_state: str,
        candidate_revision: int,
    ) -> SkillVersionHead:
        updated_at = _now()
        cursor = connection.execute(
            """
            UPDATE skill_version_heads
            SET lifecycle_state = ?, state_revision = ?, candidate_revision = ?,
                updated_at = ?
            WHERE skill_id = ? AND semantic_version = ?
              AND lifecycle_state = ? AND state_revision = ?
            """,
            (
                target_state,
                head.state_revision + 1,
                candidate_revision,
                _iso(updated_at),
                head.skill_id,
                head.semantic_version,
                head.lifecycle_state.value,
                head.state_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ExpectedRevisionError("skill head CAS failed")
        return SkillVersionHead(
            skill_id=head.skill_id,
            semantic_version=head.semantic_version,
            lifecycle_state=target_state,
            state_revision=head.state_revision + 1,
            manifest_hash=head.manifest_hash,
            candidate_id=head.candidate_id,
            candidate_revision=candidate_revision,
            updated_at=updated_at,
        )

    def _deprecate_in_transaction(
        self,
        connection: sqlite3.Connection,
        head: SkillVersionHead,
        *,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        evidence_reference_ids: tuple[str, ...],
        idempotency_key: str,
        scope_key: str | None = None,
        expected_scope_revision: int | None = None,
    ) -> tuple[SkillDeprecationRecord, SkillVersionHead]:
        created_at = _now()
        record = SkillDeprecationRecord.create(
            {
                "deprecation_id": f"deprecation_{uuid.uuid4().hex}",
                "skill_id": head.skill_id,
                "semantic_version": head.semantic_version,
                "candidate_id": head.candidate_id,
                "candidate_revision": head.candidate_revision,
                "expected_state_revision": head.state_revision,
                "target_state_revision": head.state_revision + 1,
                "scope_key": scope_key,
                "expected_scope_revision": expected_scope_revision,
                "actor_type": actor_type,
                "actor_id": actor_id,
                "reason_code": reason_code,
                "correlation_id": correlation_id,
                "evidence_reference_ids": evidence_reference_ids,
                "idempotency_key": idempotency_key,
                "created_at": created_at,
            }
        )
        self._insert_deprecation(connection, record)
        outcome = self.registry.learning._transition_in_transaction(
            connection,
            TransitionRequest(
                candidate_id=head.candidate_id,
                expected_revision=head.candidate_revision,
                target_state=CandidateState.DEPRECATED,
                actor_type=actor_type,
                actor_id=actor_id,
                reason="Skill version was explicitly deprecated.",
                reason_code=reason_code,
                correlation_id=correlation_id,
                idempotency_key=self._child_key(idempotency_key, "candidate"),
                evidence_reference_ids=evidence_reference_ids
                + (record.deprecation_id,),
                skill_lifecycle_record_id=record.deprecation_id,
            ),
            skill_lifecycle_authorized=True,
        )
        updated = self._cas_head(connection, head, "deprecated", outcome.revision)
        self.registry._append_event(
            connection,
            event_type=SkillAuditEventType.DEPRECATED,
            skill_id=head.skill_id,
            semantic_version=head.semantic_version,
            candidate_id=head.candidate_id,
            candidate_revision=outcome.revision,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason_code=reason_code,
            reference_ids=evidence_reference_ids + (record.deprecation_id,),
            created_at=created_at,
        )
        return record, updated

    @staticmethod
    def _insert_promotion(
        connection: sqlite3.Connection, record: SkillPromotionRecord
    ) -> None:
        connection.execute(
            """
            INSERT INTO skill_promotion_records(
                promotion_id, skill_id, semantic_version, candidate_id,
                candidate_revision, manifest_hash, decision, idempotency_key,
                record_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.promotion_id,
                record.skill_id,
                record.semantic_version,
                record.candidate_id,
                record.candidate_revision,
                record.manifest_hash,
                record.decision.value,
                record.idempotency_key,
                record.record_hash,
                record.model_dump_json(),
                _iso(record.created_at),
            ),
        )

    @staticmethod
    def _insert_activation(
        connection: sqlite3.Connection, record: SkillActivationRecord
    ) -> None:
        connection.execute(
            """
            INSERT INTO skill_activation_records(
                activation_id, scope_key, skill_id, semantic_version,
                previous_skill_id, previous_semantic_version,
                expected_scope_revision, target_scope_revision, manifest_hash,
                idempotency_key, record_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.activation_id,
                record.scope_key,
                record.skill_id,
                record.semantic_version,
                record.previous_skill_id,
                record.previous_semantic_version,
                record.expected_scope_revision,
                record.target_scope_revision,
                record.manifest_hash,
                record.idempotency_key,
                record.record_hash,
                record.model_dump_json(),
                _iso(record.created_at),
            ),
        )

    @staticmethod
    def _insert_deprecation(
        connection: sqlite3.Connection, record: SkillDeprecationRecord
    ) -> None:
        connection.execute(
            """
            INSERT INTO skill_deprecation_records(
                deprecation_id, skill_id, semantic_version,
                expected_state_revision, target_state_revision,
                idempotency_key, record_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.deprecation_id,
                record.skill_id,
                record.semantic_version,
                record.expected_state_revision,
                record.target_state_revision,
                record.idempotency_key,
                record.record_hash,
                record.model_dump_json(),
                _iso(record.created_at),
            ),
        )

    @staticmethod
    def _insert_rollback(
        connection: sqlite3.Connection, record: SkillRollbackRecord
    ) -> None:
        connection.execute(
            """
            INSERT INTO skill_rollback_records(
                rollback_id, scope_key, from_skill_id, from_semantic_version,
                target_skill_id, target_semantic_version,
                expected_scope_revision, target_scope_revision, activation_id,
                idempotency_key, record_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.rollback_id,
                record.scope_key,
                record.from_skill_id,
                record.from_semantic_version,
                record.target_skill_id,
                record.target_semantic_version,
                record.expected_scope_revision,
                record.target_scope_revision,
                record.activation_id,
                record.idempotency_key,
                record.record_hash,
                record.model_dump_json(),
                _iso(record.created_at),
            ),
        )

    @staticmethod
    def _write_scope(connection, previous, record: SkillActivationRecord) -> None:
        if previous is None:
            connection.execute(
                """
                INSERT INTO skill_scope_heads(
                    scope_key, active_skill_id, active_semantic_version,
                    active_manifest_hash, scope_revision, activation_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.scope_key,
                    record.skill_id,
                    record.semantic_version,
                    record.manifest_hash,
                    record.target_scope_revision,
                    record.activation_id,
                    _iso(record.created_at),
                ),
            )
            return
        cursor = connection.execute(
            """
            UPDATE skill_scope_heads
            SET active_skill_id = ?, active_semantic_version = ?,
                active_manifest_hash = ?, scope_revision = ?, activation_id = ?,
                updated_at = ?
            WHERE scope_key = ? AND scope_revision = ?
              AND active_skill_id = ? AND active_semantic_version = ?
            """,
            (
                record.skill_id,
                record.semantic_version,
                record.manifest_hash,
                record.target_scope_revision,
                record.activation_id,
                _iso(record.created_at),
                record.scope_key,
                record.expected_scope_revision,
                record.previous_skill_id,
                record.previous_semantic_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ExpectedRevisionError("skill scope CAS failed")

    @staticmethod
    def _promotion(
        connection: sqlite3.Connection, promotion_id: str
    ) -> SkillPromotionRecord:
        row = connection.execute(
            "SELECT * FROM skill_promotion_records WHERE promotion_id = ?",
            (promotion_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("promotion record not found")
        try:
            record = SkillPromotionRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError("promotion record integrity failure") from exc
        if (
            record.promotion_id != row["promotion_id"]
            or record.skill_id != row["skill_id"]
            or record.semantic_version != row["semantic_version"]
            or record.candidate_id != row["candidate_id"]
            or record.candidate_revision != int(row["candidate_revision"])
            or record.manifest_hash != row["manifest_hash"]
            or record.decision.value != row["decision"]
            or record.idempotency_key != row["idempotency_key"]
            or record.record_hash != row["record_hash"]
            or _iso(record.created_at) != row["created_at"]
        ):
            raise LearningIntegrityError("promotion record index failure")
        return record

    @staticmethod
    def _activation(
        connection: sqlite3.Connection, activation_id: str
    ) -> SkillActivationRecord:
        row = connection.execute(
            "SELECT * FROM skill_activation_records WHERE activation_id = ?",
            (activation_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("activation record not found")
        try:
            record = SkillActivationRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError("activation record integrity failure") from exc
        if (
            record.activation_id != row["activation_id"]
            or record.scope_key != row["scope_key"]
            or record.skill_id != row["skill_id"]
            or record.semantic_version != row["semantic_version"]
            or record.previous_skill_id != row["previous_skill_id"]
            or record.previous_semantic_version != row["previous_semantic_version"]
            or record.expected_scope_revision != int(row["expected_scope_revision"])
            or record.target_scope_revision != int(row["target_scope_revision"])
            or record.manifest_hash != row["manifest_hash"]
            or record.idempotency_key != row["idempotency_key"]
            or record.record_hash != row["record_hash"]
            or _iso(record.created_at) != row["created_at"]
        ):
            raise LearningIntegrityError("activation record index failure")
        return record

    @staticmethod
    def _deprecation(
        connection: sqlite3.Connection, deprecation_id: str
    ) -> SkillDeprecationRecord:
        row = connection.execute(
            "SELECT * FROM skill_deprecation_records WHERE deprecation_id = ?",
            (deprecation_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("deprecation record not found")
        try:
            record = SkillDeprecationRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError(
                "deprecation record integrity failure"
            ) from exc
        if (
            record.deprecation_id != row["deprecation_id"]
            or record.skill_id != row["skill_id"]
            or record.semantic_version != row["semantic_version"]
            or record.expected_state_revision != int(row["expected_state_revision"])
            or record.target_state_revision != int(row["target_state_revision"])
            or record.idempotency_key != row["idempotency_key"]
            or record.record_hash != row["record_hash"]
            or _iso(record.created_at) != row["created_at"]
        ):
            raise LearningIntegrityError("deprecation record index failure")
        return record

    @staticmethod
    def _rollback(
        connection: sqlite3.Connection, rollback_id: str
    ) -> SkillRollbackRecord:
        row = connection.execute(
            "SELECT * FROM skill_rollback_records WHERE rollback_id = ?",
            (rollback_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("rollback record not found")
        try:
            record = SkillRollbackRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError("rollback record integrity failure") from exc
        if (
            record.rollback_id != row["rollback_id"]
            or record.scope_key != row["scope_key"]
            or record.from_skill_id != row["from_skill_id"]
            or record.from_semantic_version != row["from_semantic_version"]
            or record.target_skill_id != row["target_skill_id"]
            or record.target_semantic_version != row["target_semantic_version"]
            or record.expected_scope_revision != int(row["expected_scope_revision"])
            or record.target_scope_revision != int(row["target_scope_revision"])
            or record.activation_id != row["activation_id"]
            or record.idempotency_key != row["idempotency_key"]
            or record.record_hash != row["record_hash"]
            or _iso(record.created_at) != row["created_at"]
        ):
            raise LearningIntegrityError("rollback record index failure")
        return record


__all__ = [
    "ActivationDecision",
    "ActivationKind",
    "ActivationOutcome",
    "HealthcheckRunner",
    "PromotionDecision",
    "PromotionOutcome",
    "RollbackOutcome",
    "SkillActivationRecord",
    "SkillDeprecationRecord",
    "SkillHealthcheckResult",
    "SkillLifecycleService",
    "SkillPromotionRecord",
    "SkillRollbackRecord",
]
