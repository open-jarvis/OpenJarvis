"""Versioned metrics derived only from persisted canonical evaluations."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.evaluation.models import (
    Digest,
    EvaluationClass,
    EvidenceSourceKind,
    Identifier,
    VerificationState,
)
from openjarvis.learning.skills.execution import (
    CanonicalSkillExecutor,
    SkillExecutionOutcome,
)
from openjarvis.learning.skills.manifest import SemanticVersion, SkillIdentifier
from openjarvis.learning.skills.registry import (
    SkillRegistry,
    SkillRegistryError,
    _digest,
    _iso,
    _now,
    _validate_identifier,
)
from openjarvis.learning.store.repository import (
    LearningIntegrityError,
    LearningRecordNotFoundError,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SkillMetricObservation(StrictFrozenModel):
    observation_id: Identifier
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    execution_id: Identifier
    evaluation_id: Identifier
    evaluation_hash: Digest
    token_usage: int = Field(default=0, ge=0)
    usage_evidence_digest: Digest | None = None
    regression_confirmed: bool = False
    regression_evidence_digest: Digest | None = None

    @model_validator(mode="after")
    def _evidence_contract(self) -> Self:
        if (self.token_usage > 0) != (self.usage_evidence_digest is not None):
            raise ValueError("non-zero token usage requires exact usage evidence")
        if self.regression_confirmed != (self.regression_evidence_digest is not None):
            raise ValueError("regression count requires exact evidence")
        return self


class _MetricPayload(StrictFrozenModel):
    snapshot_id: Identifier
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    snapshot_version: int = Field(ge=1)
    source_evaluation_ids: tuple[Identifier, ...]
    attempts: int = Field(ge=0)
    verified_successes: int = Field(ge=0)
    verified_failures: int = Field(ge=0)
    partial_outcomes: int = Field(ge=0)
    unknown_outcomes: int = Field(ge=0)
    policy_denials: int = Field(ge=0)
    approval_denials: int = Field(ge=0)
    approval_timeouts: int = Field(ge=0)
    verification_failures: int = Field(ge=0)
    canceled_outcomes: int = Field(ge=0)
    interrupted_outcomes: int = Field(ge=0)
    rollbacks: int = Field(ge=0)
    regressions: int = Field(ge=0)
    total_runtime_seconds: float = Field(ge=0)
    token_usage: int = Field(ge=0)
    tool_usage: dict[Identifier, int]
    last_verified_at: datetime | None = None
    sample_size: int = Field(ge=0)
    verified_success_rate: float | None = Field(default=None, ge=0, le=1)
    small_sample_warning: bool
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)
    _normalise_verified_at = field_validator("last_verified_at")(
        lambda value: None if value is None else _utc(value)
    )

    @field_validator("source_evaluation_ids")
    @classmethod
    def _unique_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("metric snapshot requires canonical evaluations")
        return values

    @field_validator("tool_usage")
    @classmethod
    def _tool_counts(cls, values: dict[str, int]) -> dict[str, int]:
        if any(count <= 0 for count in values.values()):
            raise ValueError("tool usage counts must be positive")
        return dict(sorted(values.items()))

    @model_validator(mode="after")
    def _metric_contract(self) -> Self:
        if self.attempts != len(self.source_evaluation_ids):
            raise ValueError("attempt denominator must equal canonical evaluations")
        if self.sample_size != self.attempts:
            raise ValueError("sample_size must expose the denominator")
        expected_rate = (
            None
            if self.sample_size == 0
            else self.verified_successes / self.sample_size
        )
        if self.verified_success_rate != expected_rate:
            raise ValueError("verified success rate or denominator mismatch")
        if self.small_sample_warning != (self.sample_size < 30):
            raise ValueError("small-sample warning mismatch")
        return self


class SkillMetricSnapshot(_MetricPayload):
    snapshot_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillMetricSnapshot:
        payload = _MetricPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "snapshot_hash": _digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"snapshot_hash"})
        if self.snapshot_hash != _digest(payload):
            raise ValueError("metric snapshot_hash mismatch")
        return self


class VerifiedSkillMetricService:
    """Append snapshots after an execution is bound to a stored evaluation."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def observe(
        self,
        observation: SkillMetricObservation,
        *,
        correlation_id: str,
        idempotency_key: str,
    ) -> SkillMetricSnapshot:
        _validate_identifier(correlation_id, "correlation_id")
        _validate_identifier(idempotency_key, "idempotency_key")
        evaluation = self.registry.learning.get_evaluation(observation.evaluation_id)
        execution = CanonicalSkillExecutor(
            self.registry, action_service=None
        ).get_execution(observation.execution_id)
        if evaluation.evaluation_hash != observation.evaluation_hash:
            raise LearningIntegrityError("metric evaluation hash mismatch")
        if (
            execution.skill_id != observation.skill_id
            or execution.semantic_version != observation.semantic_version
            or execution.task_id != evaluation.task_id
            or execution.session_id != evaluation.session_id
            or execution.correlation_id != evaluation.correlation_id
        ):
            raise SkillRegistryError(
                "metric observation does not bind one canonical execution"
            )
        evidence_digests = {item.digest for item in evaluation.evidence_references}
        if (
            observation.usage_evidence_digest is not None
            and observation.usage_evidence_digest
            not in {
                item.digest
                for item in evaluation.evidence_references
                if item.source_kind is EvidenceSourceKind.USAGE_RECORD
            }
        ):
            raise SkillRegistryError("token usage lacks canonical usage evidence")
        if (
            observation.regression_evidence_digest is not None
            and observation.regression_evidence_digest not in evidence_digests
        ):
            raise SkillRegistryError("regression lacks canonical evidence")
        request_digest = _digest(
            {
                "operation": "skill.metrics.observe",
                "observation": observation.model_dump(mode="json"),
                "correlation_id": correlation_id,
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.metrics.observe",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._snapshot(connection, replay["snapshot_id"])
            previous = self._latest(
                connection, observation.skill_id, observation.semantic_version
            )
            if previous is not None and (
                observation.evaluation_id in previous.source_evaluation_ids
            ):
                raise SkillRegistryError("canonical evaluation already counted")
            snapshot = self._next_snapshot(
                connection, previous, observation, evaluation, execution
            )
            connection.execute(
                """
                INSERT INTO skill_metric_snapshots(
                    snapshot_id, skill_id, semantic_version, snapshot_version,
                    snapshot_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.skill_id,
                    snapshot.semantic_version,
                    snapshot.snapshot_version,
                    snapshot.snapshot_hash,
                    snapshot.model_dump_json(),
                    _iso(snapshot.created_at),
                ),
            )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.metrics.observe",
                request_digest=request_digest,
                references={"snapshot_id": snapshot.snapshot_id},
            )
            return snapshot

    def latest(self, skill_id: str, semantic_version: str) -> SkillMetricSnapshot:
        with self.registry.database.reader() as connection:
            snapshot = self._latest(connection, skill_id, semantic_version)
            if snapshot is None:
                raise LearningRecordNotFoundError("skill metrics not found")
            return snapshot

    def history(
        self, skill_id: str, semantic_version: str
    ) -> tuple[SkillMetricSnapshot, ...]:
        with self.registry.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT snapshot_id FROM skill_metric_snapshots
                WHERE skill_id = ? AND semantic_version = ?
                ORDER BY snapshot_version
                """,
                (skill_id, semantic_version),
            ).fetchall()
            return tuple(self._snapshot(connection, row["snapshot_id"]) for row in rows)

    def _next_snapshot(self, connection, previous, observation, evaluation, execution):
        values = self._base_values(previous)
        values["attempts"] += 1
        values["sample_size"] += 1
        values["source_evaluation_ids"] = tuple(
            sorted(set(values["source_evaluation_ids"] + (evaluation.evaluation_id,)))
        )
        outcome = execution.outcome
        evaluation_class = evaluation.evaluation_class
        verified_success = (
            outcome
            in {
                SkillExecutionOutcome.COMPLETED,
                SkillExecutionOutcome.COMPLETED_WITH_WARNING,
            }
            and evaluation_class
            in {
                EvaluationClass.COMPLETED,
                EvaluationClass.COMPLETED_WITH_WARNING,
            }
            and evaluation.verification_state is VerificationState.PASSED
        )
        if verified_success:
            values["verified_successes"] += 1
            values["last_verified_at"] = evaluation.created_at
        elif outcome is SkillExecutionOutcome.PARTIAL or (
            evaluation_class is EvaluationClass.PARTIAL
        ):
            values["partial_outcomes"] += 1
        elif outcome is SkillExecutionOutcome.UNKNOWN or (
            evaluation_class is EvaluationClass.UNKNOWN_FAILURE
        ):
            values["unknown_outcomes"] += 1
        elif outcome is SkillExecutionOutcome.POLICY_DENIED or (
            evaluation_class is EvaluationClass.POLICY_DENIED
        ):
            values["policy_denials"] += 1
        elif outcome is SkillExecutionOutcome.APPROVAL_DENIED or (
            evaluation_class is EvaluationClass.APPROVAL_DENIED
        ):
            values["approval_denials"] += 1
        elif outcome is SkillExecutionOutcome.APPROVAL_TIMEOUT or (
            evaluation_class is EvaluationClass.APPROVAL_TIMEOUT
        ):
            values["approval_timeouts"] += 1
        elif outcome is SkillExecutionOutcome.VERIFICATION_FAILED or (
            evaluation_class is EvaluationClass.VERIFICATION_FAILED
        ):
            values["verification_failures"] += 1
            values["verified_failures"] += 1
        elif outcome is SkillExecutionOutcome.CANCELED or (
            evaluation_class is EvaluationClass.CANCELED
        ):
            values["canceled_outcomes"] += 1
        elif outcome is SkillExecutionOutcome.INTERRUPTED or (
            evaluation_class is EvaluationClass.INTERRUPTED
        ):
            values["interrupted_outcomes"] += 1
        else:
            values["verified_failures"] += 1
        values["regressions"] += int(observation.regression_confirmed)
        values["total_runtime_seconds"] += (
            execution.completed_at - execution.created_at
        ).total_seconds()
        values["token_usage"] += observation.token_usage
        tool_usage = dict(values["tool_usage"])
        for step in execution.steps:
            tool_usage[step.tool_id] = tool_usage.get(step.tool_id, 0) + 1
        values["tool_usage"] = tool_usage
        values["rollbacks"] = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM skill_rollback_records
                WHERE from_skill_id = ? AND from_semantic_version = ?
                """,
                (observation.skill_id, observation.semantic_version),
            ).fetchone()[0]
        )
        values["verified_success_rate"] = (
            values["verified_successes"] / values["sample_size"]
        )
        values["small_sample_warning"] = values["sample_size"] < 30
        values.update(
            {
                "snapshot_id": f"skill_metrics_{uuid.uuid4().hex}",
                "skill_id": observation.skill_id,
                "semantic_version": observation.semantic_version,
                "snapshot_version": 1
                if previous is None
                else previous.snapshot_version + 1,
                "created_at": _now(),
            }
        )
        return SkillMetricSnapshot.create(values)

    @staticmethod
    def _base_values(previous: SkillMetricSnapshot | None) -> dict[str, Any]:
        if previous is not None:
            return previous.model_dump(
                exclude={
                    "snapshot_id",
                    "skill_id",
                    "semantic_version",
                    "snapshot_version",
                    "snapshot_hash",
                    "created_at",
                }
            )
        return {
            "source_evaluation_ids": (),
            "attempts": 0,
            "verified_successes": 0,
            "verified_failures": 0,
            "partial_outcomes": 0,
            "unknown_outcomes": 0,
            "policy_denials": 0,
            "approval_denials": 0,
            "approval_timeouts": 0,
            "verification_failures": 0,
            "canceled_outcomes": 0,
            "interrupted_outcomes": 0,
            "rollbacks": 0,
            "regressions": 0,
            "total_runtime_seconds": 0.0,
            "token_usage": 0,
            "tool_usage": {},
            "last_verified_at": None,
            "sample_size": 0,
            "verified_success_rate": None,
            "small_sample_warning": True,
        }

    @staticmethod
    def _latest(connection, skill_id: str, semantic_version: str):
        row = connection.execute(
            """
            SELECT snapshot_id FROM skill_metric_snapshots
            WHERE skill_id = ? AND semantic_version = ?
            ORDER BY snapshot_version DESC LIMIT 1
            """,
            (skill_id, semantic_version),
        ).fetchone()
        return (
            None
            if row is None
            else VerifiedSkillMetricService._snapshot(connection, row["snapshot_id"])
        )

    @staticmethod
    def _snapshot(
        connection: sqlite3.Connection, snapshot_id: str
    ) -> SkillMetricSnapshot:
        row = connection.execute(
            "SELECT * FROM skill_metric_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("skill metric snapshot not found")
        try:
            snapshot = SkillMetricSnapshot.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError("skill metric integrity failure") from exc
        if (
            snapshot.snapshot_id != row["snapshot_id"]
            or snapshot.skill_id != row["skill_id"]
            or snapshot.semantic_version != row["semantic_version"]
            or snapshot.snapshot_version != int(row["snapshot_version"])
            or snapshot.snapshot_hash != row["snapshot_hash"]
            or _iso(snapshot.created_at) != row["created_at"]
        ):
            raise LearningIntegrityError("skill metric index failure")
        return snapshot


__all__ = [
    "SkillMetricObservation",
    "SkillMetricSnapshot",
    "VerifiedSkillMetricService",
]
