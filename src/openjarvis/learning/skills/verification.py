"""Versioned hermetic skill tests and transactional verification lifecycle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.candidates.models import CandidateState
from openjarvis.learning.evaluation.models import Digest, Identifier
from openjarvis.learning.lifecycle.models import ActorType, TransitionRequest
from openjarvis.learning.skills.manifest import SemanticVersion, SkillIdentifier
from openjarvis.learning.skills.registry import (
    SkillRegistry,
    SkillRegistryError,
    _digest,
    _iso,
    _json,
    _now,
    _validate_identifier,
)
from openjarvis.learning.skills.registry_models import (
    SkillAuditEventType,
    SkillVersionHead,
)
from openjarvis.learning.store.repository import (
    ExpectedRevisionError,
    LearningIntegrityError,
    LearningRecordNotFoundError,
)


def _hash(payload: object) -> str:
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


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SkillTestType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    INPUT_SCHEMA = "input_schema"
    OUTPUT_SCHEMA = "output_schema"
    POLICY = "policy"
    POSTCONDITION = "postcondition"
    ROLLBACK = "rollback"
    TIMEOUT = "timeout"
    CYCLE = "cycle"
    CAPABILITY = "capability"
    RISK = "risk"
    IDEMPOTENCY = "idempotency"
    RESTART = "restart"


class FixtureClass(str, Enum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class _SkillTestCasePayload(StrictFrozenModel):
    test_id: Identifier
    test_version: int = Field(ge=1)
    test_type: SkillTestType
    fixture_id: Identifier
    fixture_class: FixtureClass
    input_digest: Digest
    expected_evidence_digests: tuple[Digest, ...]
    expected_outcome: Identifier
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("expected_evidence_digests")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("test cases require expected evidence digests")
        return values


class SkillTestCase(_SkillTestCasePayload):
    content_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillTestCase:
        payload = _SkillTestCasePayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "content_hash": _hash(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if self.content_hash != _hash(payload):
            raise ValueError("skill test case content_hash mismatch")
        return self


class _SkillTestResultPayload(StrictFrozenModel):
    result_id: Identifier
    test_id: Identifier
    test_version: int = Field(ge=1)
    test_type: SkillTestType
    fixture_id: Identifier
    passed: bool
    effect_known: bool
    canonical_outcome: Identifier
    evidence_digests: tuple[Digest, ...]
    duration_seconds: float = Field(ge=0, le=300)
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("evidence_digests")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("test results require evidence digests")
        return values


class SkillTestResult(_SkillTestResultPayload):
    result_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillTestResult:
        payload = _SkillTestResultPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "result_hash": _hash(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"result_hash"})
        if self.result_hash != _hash(payload):
            raise ValueError("skill test result_hash mismatch")
        return self


class _SkillTestRunPayload(StrictFrozenModel):
    run_id: Identifier
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    candidate_id: Identifier
    candidate_revision: int = Field(ge=1)
    manifest_hash: Digest
    hermetic: Literal[True] = True
    test_cases: tuple[SkillTestCase, ...]
    test_results: tuple[SkillTestResult, ...]
    created_at: datetime
    completed_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)
    _normalise_completed_at = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def _test_contract(self) -> Self:
        if not self.test_cases:
            raise ValueError("verification run requires test cases")
        cases = {(case.test_id, case.test_version): case for case in self.test_cases}
        if len(cases) != len(self.test_cases):
            raise ValueError("test case identities must be unique")
        results = {
            (result.test_id, result.test_version): result
            for result in self.test_results
        }
        if set(results) != set(cases):
            raise ValueError("every test case requires exactly one result")
        for key, result in results.items():
            case = cases[key]
            if (
                result.test_type is not case.test_type
                or result.fixture_id != case.fixture_id
            ):
                raise ValueError("test result does not match its case")
            if not set(case.expected_evidence_digests) <= set(result.evidence_digests):
                raise ValueError("test result is missing expected evidence")
        if self.completed_at < self.created_at:
            raise ValueError("test run completion precedes creation")
        return self


class SkillTestRun(_SkillTestRunPayload):
    run_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillTestRun:
        payload = _SkillTestRunPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "run_hash": _hash(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"run_hash"})
        if self.run_hash != _hash(payload):
            raise ValueError("skill test run_hash mismatch")
        return self


class _VerificationPayload(StrictFrozenModel):
    verification_id: Identifier
    run: SkillTestRun
    status: VerificationStatus
    required_test_types: tuple[SkillTestType, ...]
    fixture_ids: tuple[Identifier, ...]
    holdout_fixture_ids: tuple[Identifier, ...]
    activation_ready: bool
    evidence_digests: tuple[Digest, ...]
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("required_test_types")
    @classmethod
    def _normalise_types(
        cls, values: tuple[SkillTestType, ...]
    ) -> tuple[SkillTestType, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @field_validator("fixture_ids", "evidence_digests")
    @classmethod
    def _required_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("verification record requires evidence and fixtures")
        return values

    @field_validator("holdout_fixture_ids")
    @classmethod
    def _normalise_holdouts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class SkillVerificationRecord(_VerificationPayload):
    verification_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillVerificationRecord:
        payload = _VerificationPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "verification_hash": _hash(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"verification_hash"})
        if self.verification_hash != _hash(payload):
            raise ValueError("skill verification_hash mismatch")
        return self


class SkillVerificationOutcome(StrictFrozenModel):
    record: SkillVerificationRecord
    candidate_revision: int = Field(ge=2)
    skill_head: SkillVersionHead
    idempotent: bool = False


REQUIRED_VERIFICATION_TYPES = frozenset(
    {
        SkillTestType.POSITIVE,
        SkillTestType.NEGATIVE,
        SkillTestType.INPUT_SCHEMA,
        SkillTestType.OUTPUT_SCHEMA,
        SkillTestType.POLICY,
        SkillTestType.CAPABILITY,
        SkillTestType.RISK,
        SkillTestType.POSTCONDITION,
    }
)


class SkillVerificationService:
    """Atomically advances registered skills through testing and verification."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def start_testing(
        self,
        *,
        skill_id: str,
        semantic_version: str,
        expected_candidate_revision: int,
        expected_state_revision: int,
        actor_type: ActorType,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        evidence_reference_ids: tuple[str, ...],
    ) -> SkillVersionHead:
        self._validate_request_ids(
            actor_id, correlation_id, idempotency_key, evidence_reference_ids
        )
        if not evidence_reference_ids:
            raise SkillRegistryError("testing requires evidence references")
        request_digest = _digest(
            {
                "operation": "skill.testing.start",
                "skill_id": skill_id,
                "semantic_version": semantic_version,
                "expected_candidate_revision": expected_candidate_revision,
                "expected_state_revision": expected_state_revision,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "correlation_id": correlation_id,
                "evidence_reference_ids": sorted(evidence_reference_ids),
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.testing.start",
                request_digest=request_digest,
            )
            if replay is not None:
                return self.registry._head(connection, skill_id, semantic_version)
            head = self.registry._head(connection, skill_id, semantic_version)
            if head.lifecycle_state.value != "draft":
                raise SkillRegistryError("only a draft skill can start testing")
            if head.state_revision != expected_state_revision:
                raise ExpectedRevisionError("skill state revision changed")
            lifecycle_record_id = f"skill_testing_{uuid.uuid4().hex}"
            outcome = self.registry.learning._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=head.candidate_id,
                    expected_revision=expected_candidate_revision,
                    target_state=CandidateState.TESTING,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="Hermetic skill verification started.",
                    reason_code="skill_testing_started",
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}.candidate",
                    evidence_reference_ids=evidence_reference_ids,
                    skill_lifecycle_record_id=lifecycle_record_id,
                ),
                skill_lifecycle_authorized=True,
            )
            updated = self._cas_head(
                connection,
                head,
                target_state="testing",
                candidate_revision=outcome.revision,
            )
            self.registry._append_event(
                connection,
                event_type=SkillAuditEventType.TEST_STARTED,
                skill_id=skill_id,
                semantic_version=semantic_version,
                candidate_id=head.candidate_id,
                candidate_revision=outcome.revision,
                correlation_id=correlation_id,
                actor_type=actor_type,
                actor_id=actor_id,
                reason_code="skill_testing_started",
                reference_ids=evidence_reference_ids + (lifecycle_record_id,),
                created_at=_now(),
            )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.testing.start",
                request_digest=request_digest,
                references={
                    "skill_id": skill_id,
                    "semantic_version": semantic_version,
                    "candidate_revision": outcome.revision,
                },
            )
            return updated

    def verify(
        self,
        record: SkillVerificationRecord,
        *,
        expected_state_revision: int,
        actor_type: ActorType,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> SkillVerificationOutcome:
        self._validate_request_ids(actor_id, correlation_id, idempotency_key, ())
        if actor_type not in {
            ActorType.SYSTEM_POLICY,
            ActorType.DETERMINISTIC_TEST,
        }:
            raise SkillRegistryError("verification requires a deterministic actor")
        self._validate_verification_record(record)
        request_digest = _digest(
            {
                "operation": "skill.verify",
                "verification_hash": record.verification_hash,
                "expected_state_revision": expected_state_revision,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "correlation_id": correlation_id,
            }
        )
        run = record.run
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.verify",
                request_digest=request_digest,
            )
            if replay is not None:
                stored = self._verification(connection, run.run_id)
                return SkillVerificationOutcome(
                    record=stored,
                    candidate_revision=int(replay["candidate_revision"]),
                    skill_head=self.registry._head(
                        connection, run.skill_id, run.semantic_version
                    ),
                    idempotent=True,
                )
            head = self.registry._head(connection, run.skill_id, run.semantic_version)
            if head.lifecycle_state.value != "testing":
                raise SkillRegistryError("skill is not in testing")
            if head.state_revision != expected_state_revision:
                raise ExpectedRevisionError("skill state revision changed")
            if (
                head.candidate_id != run.candidate_id
                or head.candidate_revision != run.candidate_revision
                or head.manifest_hash != run.manifest_hash
            ):
                raise SkillRegistryError("verification run is not pinned to the head")
            if self.registry.learning._has_open_conflict(connection, head.candidate_id):
                raise SkillRegistryError("open conflict prevents verification")
            manifest = self.registry._manifest(
                connection, run.skill_id, run.semantic_version
            )
            manifest.validate_tool_bindings(self.registry.tool_catalog)
            self._persist_verification(connection, record)
            target = (
                CandidateState.VERIFIED
                if record.status is VerificationStatus.PASSED
                else CandidateState.VERIFICATION_FAILED
            )
            lifecycle_record_id = record.verification_id
            outcome = self.registry.learning._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=head.candidate_id,
                    expected_revision=head.candidate_revision,
                    target_state=target,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="Hermetic verification completed.",
                    reason_code=f"skill_{target.value}",
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}.candidate",
                    evidence_reference_ids=(record.verification_id,)
                    + tuple(result.result_id for result in run.test_results),
                    skill_lifecycle_record_id=lifecycle_record_id,
                ),
                skill_lifecycle_authorized=True,
            )
            updated = self._cas_head(
                connection,
                head,
                target_state=target.value,
                candidate_revision=outcome.revision,
            )
            for result in run.test_results:
                self.registry._append_event(
                    connection,
                    event_type=(
                        SkillAuditEventType.TEST_PASSED
                        if result.passed
                        else SkillAuditEventType.TEST_FAILED
                    ),
                    skill_id=run.skill_id,
                    semantic_version=run.semantic_version,
                    candidate_id=run.candidate_id,
                    candidate_revision=outcome.revision,
                    correlation_id=correlation_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason_code=f"test_{result.test_type.value}",
                    reference_ids=(result.test_id, result.result_id),
                    created_at=record.created_at,
                )
            self.registry._append_event(
                connection,
                event_type=(
                    SkillAuditEventType.VERIFIED
                    if record.status is VerificationStatus.PASSED
                    else SkillAuditEventType.VERIFICATION_FAILED
                ),
                skill_id=run.skill_id,
                semantic_version=run.semantic_version,
                candidate_id=run.candidate_id,
                candidate_revision=outcome.revision,
                correlation_id=correlation_id,
                actor_type=actor_type,
                actor_id=actor_id,
                reason_code=f"skill_{target.value}",
                reference_ids=(record.verification_id, run.run_id),
                created_at=record.created_at,
            )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.verify",
                request_digest=request_digest,
                references={
                    "run_id": run.run_id,
                    "candidate_revision": outcome.revision,
                },
            )
            return SkillVerificationOutcome(
                record=record,
                candidate_revision=outcome.revision,
                skill_head=updated,
            )

    def reopen_after_failure(
        self,
        *,
        skill_id: str,
        semantic_version: str,
        expected_candidate_revision: int,
        expected_state_revision: int,
        reject: bool,
        actor_type: ActorType,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        evidence_reference_ids: tuple[str, ...],
    ) -> SkillVersionHead:
        """Return failed verification to review, or reject it, atomically."""

        self._validate_request_ids(
            actor_id, correlation_id, idempotency_key, evidence_reference_ids
        )
        if not evidence_reference_ids:
            raise SkillRegistryError("failure review requires evidence references")
        target = CandidateState.REJECTED if reject else CandidateState.UNDER_REVIEW
        request_digest = _digest(
            {
                "operation": "skill.verification.reopen",
                "skill_id": skill_id,
                "semantic_version": semantic_version,
                "expected_candidate_revision": expected_candidate_revision,
                "expected_state_revision": expected_state_revision,
                "target": target.value,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "correlation_id": correlation_id,
                "evidence_reference_ids": sorted(evidence_reference_ids),
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.verification.reopen",
                request_digest=request_digest,
            )
            if replay is not None:
                return self.registry._head(connection, skill_id, semantic_version)
            head = self.registry._head(connection, skill_id, semantic_version)
            if head.lifecycle_state.value != "verification_failed":
                raise SkillRegistryError("skill has no failed verification to review")
            if head.state_revision != expected_state_revision:
                raise ExpectedRevisionError("skill state revision changed")
            lifecycle_record_id = f"verification_review_{uuid.uuid4().hex}"
            outcome = self.registry.learning._transition_in_transaction(
                connection,
                TransitionRequest(
                    candidate_id=head.candidate_id,
                    expected_revision=expected_candidate_revision,
                    target_state=target,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="Explicit review of failed skill verification.",
                    reason_code=(
                        "verification_failure_rejected"
                        if reject
                        else "verification_failure_reopened"
                    ),
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}.candidate",
                    evidence_reference_ids=evidence_reference_ids,
                    skill_lifecycle_record_id=lifecycle_record_id,
                ),
                skill_lifecycle_authorized=True,
            )
            updated = self._cas_head(
                connection,
                head,
                target_state="rejected" if reject else "draft",
                candidate_revision=outcome.revision,
            )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.verification.reopen",
                request_digest=request_digest,
                references={
                    "skill_id": skill_id,
                    "semantic_version": semantic_version,
                    "candidate_revision": outcome.revision,
                },
            )
            return updated

    def get_verification(self, run_id: str) -> SkillVerificationRecord:
        with self.registry.database.reader() as connection:
            return self._verification(connection, run_id)

    @staticmethod
    def _validate_request_ids(
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        references: tuple[str, ...],
    ) -> None:
        for value, field in (
            (actor_id, "actor_id"),
            (correlation_id, "correlation_id"),
            (idempotency_key, "idempotency_key"),
        ):
            _validate_identifier(value, field)
        for reference in references:
            _validate_identifier(reference, "evidence_reference_id")

    @staticmethod
    def _validate_verification_record(record: SkillVerificationRecord) -> None:
        run = record.run
        present = {case.test_type for case in run.test_cases}
        results = run.test_results
        required_complete = REQUIRED_VERIFICATION_TYPES <= present
        all_passed = all(result.passed and result.effect_known for result in results)
        canonical_successes = {"completed", "completed_with_warning"}
        if any(
            result.passed and result.canonical_outcome not in canonical_successes
            for result in results
        ):
            raise SkillRegistryError(
                "test success requires a canonical completed outcome"
            )
        expected_status = (
            VerificationStatus.PASSED
            if required_complete and all_passed
            else VerificationStatus.FAILED
        )
        if record.status is not expected_status:
            raise SkillRegistryError("verification status does not match test evidence")
        if set(record.required_test_types) != REQUIRED_VERIFICATION_TYPES:
            raise SkillRegistryError("verification required-test set is incomplete")
        fixture_ids = {case.fixture_id for case in run.test_cases}
        holdouts = {
            case.fixture_id
            for case in run.test_cases
            if case.fixture_class is FixtureClass.HOLDOUT
        }
        if (
            set(record.fixture_ids) != fixture_ids
            or set(record.holdout_fixture_ids) != holdouts
        ):
            raise SkillRegistryError("verification fixture indexes are inconsistent")
        positive_successes = sum(
            result.passed and result.test_type is SkillTestType.POSITIVE
            for result in results
        )
        expected_activation_ready = (
            record.status is VerificationStatus.PASSED
            and positive_successes >= 3
            and len(fixture_ids) >= 2
            and bool(holdouts)
        )
        if record.activation_ready != expected_activation_ready:
            raise SkillRegistryError("activation readiness does not match evidence")
        evidence = {digest for result in results for digest in result.evidence_digests}
        if set(record.evidence_digests) != evidence:
            raise SkillRegistryError("verification evidence index is inconsistent")

    @staticmethod
    def _persist_verification(
        connection: sqlite3.Connection, record: SkillVerificationRecord
    ) -> None:
        run = record.run
        try:
            connection.execute(
                """
                INSERT INTO skill_verification_runs(
                    run_id, skill_id, semantic_version, candidate_id,
                    candidate_revision, manifest_hash, status,
                    fixture_ids_json, holdout_fixture_ids_json, run_hash,
                    payload_json, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.skill_id,
                    run.semantic_version,
                    run.candidate_id,
                    run.candidate_revision,
                    run.manifest_hash,
                    record.status.value,
                    _json(list(record.fixture_ids)),
                    _json(list(record.holdout_fixture_ids)),
                    run.run_hash,
                    _json(record.model_dump(mode="json")),
                    _iso(run.created_at),
                    _iso(run.completed_at),
                ),
            )
            for result in run.test_results:
                connection.execute(
                    """
                    INSERT INTO skill_test_results(
                        result_id, run_id, test_id, test_type, fixture_id,
                        passed, result_hash, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.result_id,
                        run.run_id,
                        result.test_id,
                        result.test_type.value,
                        result.fixture_id,
                        int(result.passed),
                        result.result_hash,
                        _json(result.model_dump(mode="json")),
                        _iso(result.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise SkillRegistryError("verification run identity conflict") from exc

    @staticmethod
    def _cas_head(
        connection: sqlite3.Connection,
        head: SkillVersionHead,
        *,
        target_state: str,
        candidate_revision: int,
    ) -> SkillVersionHead:
        now = _now()
        cursor = connection.execute(
            """
            UPDATE skill_version_heads
            SET lifecycle_state = ?, state_revision = ?, candidate_revision = ?,
                updated_at = ?
            WHERE skill_id = ? AND semantic_version = ?
              AND state_revision = ? AND lifecycle_state = ?
            """,
            (
                target_state,
                head.state_revision + 1,
                candidate_revision,
                _iso(now),
                head.skill_id,
                head.semantic_version,
                head.state_revision,
                head.lifecycle_state.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ExpectedRevisionError("skill head compare-and-swap failed")
        return SkillVersionHead(
            skill_id=head.skill_id,
            semantic_version=head.semantic_version,
            lifecycle_state=target_state,
            state_revision=head.state_revision + 1,
            manifest_hash=head.manifest_hash,
            candidate_id=head.candidate_id,
            candidate_revision=candidate_revision,
            updated_at=now,
        )

    @staticmethod
    def _verification(
        connection: sqlite3.Connection, run_id: str
    ) -> SkillVerificationRecord:
        row = connection.execute(
            """
            SELECT run_id, skill_id, semantic_version, candidate_id,
                   candidate_revision, manifest_hash, status,
                   fixture_ids_json, holdout_fixture_ids_json, run_hash,
                   payload_json, created_at, completed_at
            FROM skill_verification_runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("skill verification run not found")
        try:
            record = SkillVerificationRecord.model_validate(
                json.loads(row["payload_json"])
            )
        except Exception as exc:
            raise LearningIntegrityError(
                "skill verification integrity failure"
            ) from exc
        run = record.run
        if (
            run.run_id != row["run_id"]
            or run.skill_id != row["skill_id"]
            or run.semantic_version != row["semantic_version"]
            or run.candidate_id != row["candidate_id"]
            or run.candidate_revision != int(row["candidate_revision"])
            or run.manifest_hash != row["manifest_hash"]
            or record.status.value != row["status"]
            or list(record.fixture_ids) != json.loads(row["fixture_ids_json"])
            or list(record.holdout_fixture_ids)
            != json.loads(row["holdout_fixture_ids_json"])
            or run.run_hash != row["run_hash"]
            or _iso(run.created_at) != row["created_at"]
            or _iso(run.completed_at) != row["completed_at"]
        ):
            raise LearningIntegrityError("skill verification index integrity failure")
        rows = connection.execute(
            """
            SELECT result_id, test_id, test_type, fixture_id, passed,
                   result_hash, payload_json, created_at
            FROM skill_test_results WHERE run_id = ? ORDER BY result_id
            """,
            (run_id,),
        ).fetchall()
        stored_results: list[SkillTestResult] = []
        for result_row in rows:
            try:
                result = SkillTestResult.model_validate(
                    json.loads(result_row["payload_json"])
                )
            except Exception as exc:
                raise LearningIntegrityError(
                    "skill test result integrity failure"
                ) from exc
            if (
                result.result_id != result_row["result_id"]
                or result.test_id != result_row["test_id"]
                or result.test_type.value != result_row["test_type"]
                or result.fixture_id != result_row["fixture_id"]
                or int(result.passed) != int(result_row["passed"])
                or result.result_hash != result_row["result_hash"]
                or _iso(result.created_at) != result_row["created_at"]
            ):
                raise LearningIntegrityError(
                    "skill test result index integrity failure"
                )
            stored_results.append(result)
        if tuple(sorted(stored_results, key=lambda item: item.result_id)) != tuple(
            sorted(run.test_results, key=lambda item: item.result_id)
        ):
            raise LearningIntegrityError("skill verification results are incomplete")
        return record


__all__ = [
    "FixtureClass",
    "REQUIRED_VERIFICATION_TYPES",
    "SkillTestCase",
    "SkillTestResult",
    "SkillTestRun",
    "SkillTestType",
    "SkillVerificationOutcome",
    "SkillVerificationRecord",
    "SkillVerificationService",
    "VerificationStatus",
]
