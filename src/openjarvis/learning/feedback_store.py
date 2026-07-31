"""Revisioned, task-bound feedback that cannot authorize or verify actions."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.phase7_store import (
    Phase7IntegrityError,
    Phase7RecordNotFound,
    Phase7RevisionConflict,
    Phase7StoreCoordinator,
    digest,
    iso,
    safe_metadata,
    utc_now,
    validate_digest,
    validate_identifier,
)
from openjarvis.learning.store.sqlite import SQLiteLearningDatabase

Identifier = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FeedbackType(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIALLY_CORRECT = "partially_correct"
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    ACTION_SUCCEEDED = "action_succeeded"
    ACTION_FAILED = "action_failed"
    CORRECTION = "correction"
    CANDIDATE_REJECTED = "candidate_rejected"
    SKILL_SUGGESTED = "skill_suggested"


class FeedbackSourcePriority(str, Enum):
    EXPLICIT_USER_CORRECTION = "explicit_user_correction"
    EXPLICIT_USER_FEEDBACK = "explicit_user_feedback"


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _FeedbackPayload(StrictFrozenModel):
    feedback_id: Identifier
    revision: int = Field(ge=1)
    task_id: Identifier
    session_id: Identifier
    correlation_id: Identifier
    answer_id: Identifier | None = None
    execution_id: Identifier | None = None
    actor: Identifier
    feedback_type: FeedbackType
    structured_content: dict[str, Any]
    source_digest: Digest
    source_priority: FeedbackSourcePriority
    supersedes_revision: int | None = Field(default=None, ge=1)
    created_at: datetime
    revoked_at: datetime | None = None

    @field_validator("structured_content")
    @classmethod
    def _safe_content(cls, value: dict[str, Any]) -> dict[str, Any]:
        normalized = safe_metadata(value)
        if not isinstance(normalized, dict) or not normalized:
            raise ValueError("structured_content must contain explicit feedback")
        return normalized

    @model_validator(mode="after")
    def _contract(self) -> Self:
        if (self.answer_id is None) == (self.execution_id is None):
            raise ValueError("feedback must bind to one answer_id or execution_id")
        if self.revision == 1 and self.supersedes_revision is not None:
            raise ValueError("revision 1 cannot supersede another revision")
        if self.revision > 1 and self.supersedes_revision != self.revision - 1:
            raise ValueError("feedback revisions must form an unbroken chain")
        expected_priority = (
            FeedbackSourcePriority.EXPLICIT_USER_CORRECTION
            if self.feedback_type is FeedbackType.CORRECTION
            else FeedbackSourcePriority.EXPLICIT_USER_FEEDBACK
        )
        if self.source_priority is not expected_priority:
            raise ValueError("feedback source priority does not match its type")
        return self


class FeedbackRecord(_FeedbackPayload):
    feedback_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, object]) -> "FeedbackRecord":
        payload = _FeedbackPayload.model_validate(values)
        serialized = payload.model_dump(mode="json")
        return cls.model_validate({**serialized, "feedback_hash": digest(serialized)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"feedback_hash"})
        if digest(payload) != self.feedback_hash:
            raise ValueError("feedback_hash mismatch")
        return self


class CandidateReviewHint(StrictFrozenModel):
    hint_id: Identifier
    feedback_id: Identifier
    feedback_revision: int = Field(ge=1)
    candidate_type: Identifier
    source_priority: FeedbackSourcePriority
    review_required: bool = True
    created_at: datetime
    hint_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, object]) -> "CandidateReviewHint":
        draft = cls.model_construct(**dict(values), hint_hash="0" * 64)
        payload = draft.model_dump(mode="json", exclude={"hint_hash"})
        return cls.model_validate({**payload, "hint_hash": digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"hint_hash"})
        if digest(payload) != self.hint_hash:
            raise ValueError("hint_hash mismatch")
        return self


class FeedbackOutcome(StrictFrozenModel):
    record: FeedbackRecord
    candidate_hint: CandidateReviewHint | None = None
    idempotent: bool = False


class RevisionedFeedbackService:
    """Append, revise, and revoke feedback without granting authority."""

    def __init__(self, database: SQLiteLearningDatabase) -> None:
        self.database = database
        self.coordinator = Phase7StoreCoordinator(database)

    def record(
        self,
        *,
        task_id: str,
        session_id: str,
        correlation_id: str,
        answer_id: str | None,
        execution_id: str | None,
        actor: str,
        feedback_type: FeedbackType,
        structured_content: Mapping[str, Any],
        source_digest: str,
        idempotency_key: str,
        expected_revision: int = 0,
    ) -> FeedbackOutcome:
        if expected_revision != 0:
            raise Phase7RevisionConflict("new feedback requires expected_revision=0")
        for value, field_name in (
            (task_id, "task_id"),
            (session_id, "session_id"),
            (correlation_id, "correlation_id"),
            (actor, "actor"),
            (idempotency_key, "idempotency_key"),
        ):
            validate_identifier(value, field_name)
        if answer_id is not None:
            validate_identifier(answer_id, "answer_id")
        if execution_id is not None:
            validate_identifier(execution_id, "execution_id")
        validate_digest(source_digest, "source_digest")
        content = safe_metadata(dict(structured_content))
        request_digest = digest(
            {
                "task_id": task_id,
                "session_id": session_id,
                "correlation_id": correlation_id,
                "answer_id": answer_id,
                "execution_id": execution_id,
                "actor": actor,
                "feedback_type": feedback_type.value,
                "structured_content": content,
                "source_digest": source_digest,
            }
        )
        with self.database.transaction() as connection:
            replay = self.coordinator.replay(
                connection,
                namespace="feedback",
                idempotency_key=idempotency_key,
                operation="feedback.record",
                request_digest=request_digest,
            )
            if replay is not None:
                return FeedbackOutcome(
                    record=self._record(connection, replay["feedback_id"], 1),
                    candidate_hint=self._hint_for(connection, replay["feedback_id"], 1),
                    idempotent=True,
                )
            now = utc_now()
            record = FeedbackRecord.create(
                {
                    "feedback_id": f"feedback_{uuid.uuid4().hex}",
                    "revision": 1,
                    "task_id": task_id,
                    "session_id": session_id,
                    "correlation_id": correlation_id,
                    "answer_id": answer_id,
                    "execution_id": execution_id,
                    "actor": actor,
                    "feedback_type": feedback_type,
                    "structured_content": content,
                    "source_digest": source_digest,
                    "source_priority": self._priority(feedback_type),
                    "created_at": now,
                }
            )
            self._insert_record(connection, record)
            connection.execute(
                """
                INSERT INTO feedback_heads(
                    feedback_id, current_revision, current_feedback_hash,
                    task_id, session_id, correlation_id, revoked, updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, 0, ?)
                """,
                (
                    record.feedback_id,
                    record.feedback_hash,
                    task_id,
                    session_id,
                    correlation_id,
                    iso(now),
                ),
            )
            hint = self._create_hint(connection, record)
            self.coordinator.append_audit(
                connection,
                event_type="feedback.recorded",
                task_id=task_id,
                session_id=session_id,
                correlation_id=correlation_id,
                actor=actor,
                reference_ids=(record.feedback_id,)
                + ((hint.hint_id,) if hint is not None else ()),
                created_at=now,
            )
            self.coordinator.complete(
                connection,
                namespace="feedback",
                idempotency_key=idempotency_key,
                operation="feedback.record",
                request_digest=request_digest,
                result_references={"feedback_id": record.feedback_id},
                created_at=now,
            )
            return FeedbackOutcome(record=record, candidate_hint=hint)

    def revise(
        self,
        feedback_id: str,
        *,
        expected_revision: int,
        actor: str,
        feedback_type: FeedbackType,
        structured_content: Mapping[str, Any],
        correlation_id: str,
        idempotency_key: str,
    ) -> FeedbackOutcome:
        if expected_revision < 1:
            raise Phase7RevisionConflict("feedback revision must be positive")
        for value, field_name in (
            (feedback_id, "feedback_id"),
            (actor, "actor"),
            (correlation_id, "correlation_id"),
            (idempotency_key, "idempotency_key"),
        ):
            validate_identifier(value, field_name)
        content = safe_metadata(dict(structured_content))
        request_digest = digest(
            {
                "feedback_id": feedback_id,
                "expected_revision": expected_revision,
                "actor": actor,
                "feedback_type": feedback_type.value,
                "structured_content": content,
                "correlation_id": correlation_id,
            }
        )
        with self.database.transaction() as connection:
            replay = self.coordinator.replay(
                connection,
                namespace="feedback",
                idempotency_key=idempotency_key,
                operation="feedback.revise",
                request_digest=request_digest,
            )
            if replay is not None:
                revision = int(replay["revision"])
                return FeedbackOutcome(
                    record=self._record(connection, feedback_id, revision),
                    candidate_hint=self._hint_for(connection, feedback_id, revision),
                    idempotent=True,
                )
            previous = self._head(connection, feedback_id, expected_revision)
            if previous.revoked_at is not None:
                raise Phase7RevisionConflict("revoked feedback cannot be revised")
            now = utc_now()
            record = FeedbackRecord.create(
                {
                    "feedback_id": feedback_id,
                    "revision": expected_revision + 1,
                    "task_id": previous.task_id,
                    "session_id": previous.session_id,
                    "correlation_id": correlation_id,
                    "answer_id": previous.answer_id,
                    "execution_id": previous.execution_id,
                    "actor": actor,
                    "feedback_type": feedback_type,
                    "structured_content": content,
                    "source_digest": previous.source_digest,
                    "source_priority": self._priority(feedback_type),
                    "supersedes_revision": expected_revision,
                    "created_at": now,
                }
            )
            self._insert_record(connection, record)
            self._cas_head(connection, record, expected_revision)
            hint = self._create_hint(connection, record)
            self.coordinator.append_audit(
                connection,
                event_type="feedback.revised",
                task_id=record.task_id,
                session_id=record.session_id,
                correlation_id=correlation_id,
                actor=actor,
                reference_ids=(record.feedback_id,)
                + ((hint.hint_id,) if hint is not None else ()),
                created_at=now,
            )
            self.coordinator.complete(
                connection,
                namespace="feedback",
                idempotency_key=idempotency_key,
                operation="feedback.revise",
                request_digest=request_digest,
                result_references={
                    "feedback_id": feedback_id,
                    "revision": record.revision,
                },
                created_at=now,
            )
            return FeedbackOutcome(record=record, candidate_hint=hint)

    def revoke(
        self,
        feedback_id: str,
        *,
        expected_revision: int,
        actor: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> FeedbackOutcome:
        request_digest = digest(
            {
                "feedback_id": feedback_id,
                "expected_revision": expected_revision,
                "actor": actor,
                "correlation_id": correlation_id,
            }
        )
        with self.database.transaction() as connection:
            replay = self.coordinator.replay(
                connection,
                namespace="feedback",
                idempotency_key=idempotency_key,
                operation="feedback.revoke",
                request_digest=request_digest,
            )
            if replay is not None:
                return FeedbackOutcome(
                    record=self._record(
                        connection, feedback_id, int(replay["revision"])
                    ),
                    idempotent=True,
                )
            previous = self._head(connection, feedback_id, expected_revision)
            if previous.revoked_at is not None:
                raise Phase7RevisionConflict("feedback is already revoked")
            now = utc_now()
            record = FeedbackRecord.create(
                {
                    **previous.model_dump(
                        mode="python",
                        exclude={
                            "revision",
                            "supersedes_revision",
                            "created_at",
                            "revoked_at",
                            "feedback_hash",
                            "actor",
                            "correlation_id",
                        },
                    ),
                    "revision": expected_revision + 1,
                    "supersedes_revision": expected_revision,
                    "actor": actor,
                    "correlation_id": correlation_id,
                    "created_at": now,
                    "revoked_at": now,
                }
            )
            self._insert_record(connection, record)
            self._cas_head(connection, record, expected_revision)
            self.coordinator.append_audit(
                connection,
                event_type="feedback.revoked",
                task_id=record.task_id,
                session_id=record.session_id,
                correlation_id=correlation_id,
                actor=actor,
                reference_ids=(record.feedback_id,),
                created_at=now,
            )
            self.coordinator.complete(
                connection,
                namespace="feedback",
                idempotency_key=idempotency_key,
                operation="feedback.revoke",
                request_digest=request_digest,
                result_references={
                    "feedback_id": feedback_id,
                    "revision": record.revision,
                },
                created_at=now,
            )
            return FeedbackOutcome(record=record)

    def get(self, feedback_id: str, revision: int | None = None) -> FeedbackRecord:
        with self.database.reader() as connection:
            if revision is None:
                row = connection.execute(
                    "SELECT current_revision FROM feedback_heads WHERE feedback_id = ?",
                    (feedback_id,),
                ).fetchone()
                if row is None:
                    raise Phase7RecordNotFound("feedback not found")
                revision = int(row["current_revision"])
            return self._record(connection, feedback_id, revision)

    def history(self, feedback_id: str) -> tuple[FeedbackRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT revision FROM feedback_revisions
                WHERE feedback_id = ? ORDER BY revision
                """,
                (feedback_id,),
            ).fetchall()
            if not rows:
                raise Phase7RecordNotFound("feedback not found")
            return tuple(
                self._record(connection, feedback_id, int(row["revision"]))
                for row in rows
            )

    def list_for_task(self, task_id: str) -> tuple[FeedbackRecord, ...]:
        validate_identifier(task_id, "task_id")
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT h.feedback_id, h.current_revision
                FROM feedback_heads h WHERE h.task_id = ?
                ORDER BY h.updated_at DESC, h.feedback_id DESC
                """,
                (task_id,),
            ).fetchall()
            return tuple(
                self._record(
                    connection, row["feedback_id"], int(row["current_revision"])
                )
                for row in rows
            )

    def hint_for(self, feedback_id: str, revision: int) -> CandidateReviewHint | None:
        with self.database.reader() as connection:
            return self._hint_for(connection, feedback_id, revision)

    @staticmethod
    def _priority(feedback_type: FeedbackType) -> FeedbackSourcePriority:
        return (
            FeedbackSourcePriority.EXPLICIT_USER_CORRECTION
            if feedback_type is FeedbackType.CORRECTION
            else FeedbackSourcePriority.EXPLICIT_USER_FEEDBACK
        )

    @staticmethod
    def _hint_candidate_type(feedback_type: FeedbackType) -> str | None:
        return {
            FeedbackType.CORRECTION: "user_correction",
            FeedbackType.SKILL_SUGGESTED: "skill",
            FeedbackType.CANDIDATE_REJECTED: "review_warning",
            FeedbackType.INCORRECT: "failure_pattern",
            FeedbackType.ACTION_FAILED: "failure_pattern",
        }.get(feedback_type)

    def _create_hint(
        self, connection: sqlite3.Connection, record: FeedbackRecord
    ) -> CandidateReviewHint | None:
        candidate_type = self._hint_candidate_type(record.feedback_type)
        if candidate_type is None or record.revoked_at is not None:
            return None
        hint = CandidateReviewHint.create(
            {
                "hint_id": f"feedback_hint_{uuid.uuid4().hex}",
                "feedback_id": record.feedback_id,
                "feedback_revision": record.revision,
                "candidate_type": candidate_type,
                "source_priority": record.source_priority,
                "review_required": True,
                "created_at": record.created_at,
            }
        )
        connection.execute(
            """
            INSERT INTO feedback_candidate_hints(
                hint_id, feedback_id, feedback_revision, candidate_type,
                source_priority, hint_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hint.hint_id,
                hint.feedback_id,
                hint.feedback_revision,
                hint.candidate_type,
                hint.source_priority.value,
                hint.hint_hash,
                hint.model_dump_json(),
                iso(hint.created_at),
            ),
        )
        return hint

    @staticmethod
    def _insert_record(connection: sqlite3.Connection, record: FeedbackRecord) -> None:
        connection.execute(
            """
            INSERT INTO feedback_revisions(
                feedback_id, revision, task_id, session_id, correlation_id,
                answer_id, execution_id, actor, feedback_type, source_digest,
                supersedes_revision, revoked_at, feedback_hash,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.feedback_id,
                record.revision,
                record.task_id,
                record.session_id,
                record.correlation_id,
                record.answer_id,
                record.execution_id,
                record.actor,
                record.feedback_type.value,
                record.source_digest,
                record.supersedes_revision,
                iso(record.revoked_at) if record.revoked_at is not None else None,
                record.feedback_hash,
                record.model_dump_json(),
                iso(record.created_at),
            ),
        )

    @staticmethod
    def _cas_head(
        connection: sqlite3.Connection,
        record: FeedbackRecord,
        expected_revision: int,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE feedback_heads SET
                current_revision = ?, current_feedback_hash = ?,
                correlation_id = ?, revoked = ?, updated_at = ?
            WHERE feedback_id = ? AND current_revision = ?
            """,
            (
                record.revision,
                record.feedback_hash,
                record.correlation_id,
                int(record.revoked_at is not None),
                iso(record.created_at),
                record.feedback_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise Phase7RevisionConflict("feedback revision changed")

    def _head(
        self,
        connection: sqlite3.Connection,
        feedback_id: str,
        expected_revision: int,
    ) -> FeedbackRecord:
        row = connection.execute(
            "SELECT current_revision FROM feedback_heads WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()
        if row is None:
            raise Phase7RecordNotFound("feedback not found")
        if int(row["current_revision"]) != expected_revision:
            raise Phase7RevisionConflict("feedback revision changed")
        return self._record(connection, feedback_id, expected_revision)

    @staticmethod
    def _record(
        connection: sqlite3.Connection, feedback_id: str, revision: int
    ) -> FeedbackRecord:
        row = connection.execute(
            """
            SELECT payload_json, feedback_hash FROM feedback_revisions
            WHERE feedback_id = ? AND revision = ?
            """,
            (feedback_id, revision),
        ).fetchone()
        if row is None:
            raise Phase7RecordNotFound("feedback revision not found")
        try:
            record = FeedbackRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise Phase7IntegrityError("feedback revision decode failed") from exc
        if record.feedback_hash != row["feedback_hash"]:
            raise Phase7IntegrityError("feedback revision index mismatch")
        return record

    @staticmethod
    def _hint_for(
        connection: sqlite3.Connection, feedback_id: str, revision: int
    ) -> CandidateReviewHint | None:
        row = connection.execute(
            """
            SELECT payload_json, hint_hash FROM feedback_candidate_hints
            WHERE feedback_id = ? AND feedback_revision = ?
            """,
            (feedback_id, revision),
        ).fetchone()
        if row is None:
            return None
        try:
            hint = CandidateReviewHint.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise Phase7IntegrityError("feedback hint decode failed") from exc
        if hint.hint_hash != row["hint_hash"]:
            raise Phase7IntegrityError("feedback hint index mismatch")
        return hint


__all__ = [
    "CandidateReviewHint",
    "FeedbackOutcome",
    "FeedbackRecord",
    "FeedbackSourcePriority",
    "FeedbackType",
    "RevisionedFeedbackService",
]
