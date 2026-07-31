"""Explicit, atomic conflict review for persisted learning candidates."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from openjarvis.learning.candidates.models import (
    CandidateState,
    CandidateType,
    Digest,
    Identifier,
    ShortText,
)
from openjarvis.learning.lifecycle.models import (
    ActorType,
    QuarantineResolution,
    TransitionRequest,
)
from openjarvis.learning.store.models import AuditEventType
from openjarvis.learning.store.repository import (
    LearningIntegrityError,
    LearningRecordNotFoundError,
    LearningRepository,
    LearningStoreError,
    _iso,
    _json_time,
    _now,
)


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


class ConflictResolutionError(LearningStoreError):
    """An explicit conflict decision violated the review contract."""


class ConflictResolutionDecision(str, Enum):
    KEEP_BOTH_SCOPED = "keep_both_scoped"
    REJECT_LEFT = "reject_left"
    REJECT_RIGHT = "reject_right"
    SUPERSEDE_LEFT = "supersede_left"
    SUPERSEDE_RIGHT = "supersede_right"
    UNRESOLVED = "unresolved"


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ConflictResolutionRequest(StrictFrozenModel):
    conflict_id: Identifier
    candidate_ids: tuple[Identifier, Identifier]
    candidate_revisions: tuple[int, int]
    actor_type: ActorType
    actor_id: Identifier
    decision: ConflictResolutionDecision
    reason: ShortText
    reason_code: Identifier
    evidence_digests: tuple[Digest, ...]
    correlation_id: Identifier
    idempotency_key: Identifier

    @field_validator("candidate_ids")
    @classmethod
    def _candidate_pair(cls, values: tuple[str, str]) -> tuple[str, str]:
        if values[0] == values[1]:
            raise ValueError("conflict resolution requires two candidates")
        return values

    @field_validator("candidate_revisions")
    @classmethod
    def _positive_revisions(cls, values: tuple[int, int]) -> tuple[int, int]:
        if any(value < 1 for value in values):
            raise ValueError("candidate revisions must be positive")
        return values

    @field_validator("evidence_digests")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("conflict review requires evidence digests")
        return values

    def semantic_digest(self) -> str:
        return _digest(self.model_dump(mode="json"))


class ConflictResolutionRecord(StrictFrozenModel):
    resolution_id: Identifier
    conflict_id: Identifier
    candidate_ids: tuple[Identifier, Identifier]
    candidate_revisions: tuple[int, int]
    actor_type: ActorType
    actor_id: Identifier
    decision: ConflictResolutionDecision
    reason: ShortText
    reason_code: Identifier
    evidence_digests: tuple[Digest, ...]
    correlation_id: Identifier
    idempotency_key: Identifier
    created_at: datetime
    resolution_hash: Digest

    _normalise_created_at = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        if self.resolution_hash != self.recompute_hash():
            raise ValueError("conflict resolution_hash mismatch")
        return self

    def semantic_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"resolution_hash"})

    def recompute_hash(self) -> str:
        return _digest(self.semantic_payload())


class ConflictResolutionOutcome(StrictFrozenModel):
    record: ConflictResolutionRecord
    candidate_revisions: tuple[int, int]
    closed: bool
    idempotent: bool = False


class ConflictReviewService:
    """Persist a human or deterministic conflict decision in one transaction."""

    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def resolve(self, request: ConflictResolutionRequest) -> ConflictResolutionOutcome:
        request_digest = request.semantic_digest()
        with self.repository.database.transaction() as connection:
            replay = self.repository._check_idempotency(
                connection,
                idempotency_key=request.idempotency_key,
                operation="candidate.conflict.resolve",
                request_digest=request_digest,
            )
            if replay is not None:
                record = self._record(connection, replay["resolution_id"])
                return ConflictResolutionOutcome(
                    record=record,
                    candidate_revisions=tuple(replay["candidate_revisions"]),
                    closed=bool(replay["closed"]),
                    idempotent=True,
                )
            row = connection.execute(
                """
                SELECT conflict_id, candidate_a_id, candidate_b_id
                FROM candidate_conflict_links
                WHERE conflict_id = ? AND is_open = 1
                """,
                (request.conflict_id,),
            ).fetchone()
            if row is None:
                raise LearningRecordNotFoundError("open conflict not found")
            stored_ids = (row["candidate_a_id"], row["candidate_b_id"])
            if request.candidate_ids != stored_ids:
                raise ConflictResolutionError("conflict candidate identities changed")
            if connection.execute(
                """
                SELECT 1 FROM candidate_conflict_resolutions
                WHERE conflict_id = ? AND decision <> 'unresolved'
                """,
                (request.conflict_id,),
            ).fetchone():
                raise ConflictResolutionError("conflict is already resolved")
            candidates = tuple(
                self.repository._get_head_candidate(connection, candidate_id)
                for candidate_id in request.candidate_ids
            )
            if tuple(candidate.revision for candidate in candidates) != (
                request.candidate_revisions
            ):
                raise ConflictResolutionError("conflict candidate revision changed")
            if any(
                candidate.state is not CandidateState.QUARANTINED
                for candidate in candidates
            ):
                raise ConflictResolutionError("conflict candidates must be quarantined")
            supersede = request.decision in {
                ConflictResolutionDecision.SUPERSEDE_LEFT,
                ConflictResolutionDecision.SUPERSEDE_RIGHT,
            }
            if supersede and any(
                candidate.candidate_type is not CandidateType.SKILL
                for candidate in candidates
            ):
                raise ConflictResolutionError("only skill candidates may be superseded")

            created_at = _now()
            resolution_id = f"conflict_resolution_{uuid.uuid4().hex}"
            record_payload = {
                "resolution_id": resolution_id,
                "conflict_id": request.conflict_id,
                "candidate_ids": request.candidate_ids,
                "candidate_revisions": request.candidate_revisions,
                "actor_type": request.actor_type,
                "actor_id": request.actor_id,
                "decision": request.decision,
                "reason": request.reason,
                "reason_code": request.reason_code,
                "evidence_digests": request.evidence_digests,
                "correlation_id": request.correlation_id,
                "idempotency_key": request.idempotency_key,
                "created_at": _json_time(created_at),
            }
            hash_payload = {
                **record_payload,
                "candidate_ids": list(request.candidate_ids),
                "candidate_revisions": list(request.candidate_revisions),
                "actor_type": request.actor_type.value,
                "decision": request.decision.value,
                "evidence_digests": list(request.evidence_digests),
            }
            record = ConflictResolutionRecord(
                **record_payload,
                resolution_hash=_digest(hash_payload),
            )
            closed = request.decision is not ConflictResolutionDecision.UNRESOLVED
            revised = request.candidate_revisions
            if closed:
                revised = self._transition_candidates(
                    connection, request, record, candidates
                )
            connection.execute(
                """
                INSERT INTO candidate_conflict_resolutions(
                    resolution_id, conflict_id, left_candidate_id, left_revision,
                    right_candidate_id, right_revision, decision,
                    idempotency_key, resolution_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.resolution_id,
                    record.conflict_id,
                    record.candidate_ids[0],
                    record.candidate_revisions[0],
                    record.candidate_ids[1],
                    record.candidate_revisions[1],
                    record.decision.value,
                    record.idempotency_key,
                    record.resolution_hash,
                    record.model_dump_json(),
                    _iso(record.created_at),
                ),
            )
            if closed:
                self.repository._append_event(
                    connection,
                    event_type=AuditEventType.CONFLICT_RESOLVED,
                    correlation_id=request.correlation_id,
                    reason_code=request.reason_code,
                    reference_ids=(record.conflict_id, record.resolution_id),
                    actor_type=request.actor_type,
                    actor_id=request.actor_id,
                )
            self.repository._complete_idempotency(
                connection,
                idempotency_key=request.idempotency_key,
                operation="candidate.conflict.resolve",
                request_digest=request_digest,
                references={
                    "resolution_id": record.resolution_id,
                    "candidate_revisions": list(revised),
                    "closed": closed,
                },
            )
            return ConflictResolutionOutcome(
                record=record,
                candidate_revisions=revised,
                closed=closed,
            )

    def _transition_candidates(
        self,
        connection: sqlite3.Connection,
        request: ConflictResolutionRequest,
        record: ConflictResolutionRecord,
        candidates: tuple,
    ) -> tuple[int, int]:
        targets = self._targets(request.decision)
        outcomes = []
        for index, (candidate, target) in enumerate(zip(candidates, targets)):
            resolutions = tuple(
                QuarantineResolution(
                    resolution_id=f"{record.resolution_id}_{reason.value}",
                    quarantine_reason=reason,
                    evidence_digest=request.evidence_digests[0],
                    summary="Conflict reason addressed by explicit review.",
                )
                for reason in candidate.quarantine_reasons
            )
            outcome = self.repository._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=candidate.candidate_id,
                    expected_revision=candidate.revision,
                    target_state=target,
                    actor_type=request.actor_type,
                    actor_id=request.actor_id,
                    reason=request.reason,
                    reason_code=request.reason_code,
                    correlation_id=request.correlation_id,
                    idempotency_key=f"{request.idempotency_key}.candidate{index}",
                    evidence_reference_ids=(record.resolution_id,),
                    skill_lifecycle_record_id=(
                        record.resolution_id
                        if target is CandidateState.DEPRECATED
                        else None
                    ),
                    quarantine_resolution_records=(
                        resolutions if target is CandidateState.UNDER_REVIEW else ()
                    ),
                ),
                skill_lifecycle_authorized=(target is CandidateState.DEPRECATED),
                resolving_conflict=True,
            )
            outcomes.append(outcome)
        return (outcomes[0].revision, outcomes[1].revision)

    def get_resolution(self, resolution_id: str) -> ConflictResolutionRecord:
        with self.repository.database.reader() as connection:
            return self._record(connection, resolution_id)

    @staticmethod
    def _targets(
        decision: ConflictResolutionDecision,
    ) -> tuple[CandidateState, CandidateState]:
        mapping = {
            ConflictResolutionDecision.KEEP_BOTH_SCOPED: (
                CandidateState.UNDER_REVIEW,
                CandidateState.UNDER_REVIEW,
            ),
            ConflictResolutionDecision.REJECT_LEFT: (
                CandidateState.REJECTED,
                CandidateState.UNDER_REVIEW,
            ),
            ConflictResolutionDecision.REJECT_RIGHT: (
                CandidateState.UNDER_REVIEW,
                CandidateState.REJECTED,
            ),
            ConflictResolutionDecision.SUPERSEDE_LEFT: (
                CandidateState.DEPRECATED,
                CandidateState.UNDER_REVIEW,
            ),
            ConflictResolutionDecision.SUPERSEDE_RIGHT: (
                CandidateState.UNDER_REVIEW,
                CandidateState.DEPRECATED,
            ),
        }
        try:
            return mapping[decision]
        except KeyError as exc:
            raise ConflictResolutionError(
                "unresolved has no transition targets"
            ) from exc

    @staticmethod
    def _record(
        connection: sqlite3.Connection, resolution_id: str
    ) -> ConflictResolutionRecord:
        row = connection.execute(
            """
            SELECT conflict_id, left_candidate_id, left_revision,
                   right_candidate_id, right_revision, decision,
                   idempotency_key, resolution_hash, payload_json, created_at
            FROM candidate_conflict_resolutions WHERE resolution_id = ?
            """,
            (resolution_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("conflict resolution not found")
        try:
            record = ConflictResolutionRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError(
                "conflict resolution integrity failure"
            ) from exc
        if (
            record.conflict_id != row["conflict_id"]
            or record.candidate_ids
            != (row["left_candidate_id"], row["right_candidate_id"])
            or record.candidate_revisions
            != (int(row["left_revision"]), int(row["right_revision"]))
            or record.decision.value != row["decision"]
            or record.idempotency_key != row["idempotency_key"]
            or record.resolution_hash != row["resolution_hash"]
            or _iso(record.created_at) != row["created_at"]
        ):
            raise LearningIntegrityError("conflict resolution index integrity failure")
        return record


__all__ = [
    "ConflictResolutionDecision",
    "ConflictResolutionError",
    "ConflictResolutionOutcome",
    "ConflictResolutionRecord",
    "ConflictResolutionRequest",
    "ConflictReviewService",
]
