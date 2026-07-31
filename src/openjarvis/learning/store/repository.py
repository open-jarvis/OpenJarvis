"""Transactional repository for immutable learning records and revisions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from openjarvis.learning.candidates.conflicts import detect_conflicts
from openjarvis.learning.candidates.independence import merge_groups
from openjarvis.learning.candidates.models import (
    CandidateState,
    ConflictLink,
    DuplicateReason,
    ExtractionResult,
    LearningCandidate,
    MetadataReference,
    QuarantineReason,
    SuccessfulSolutionContent,
)
from openjarvis.learning.evaluation.models import ConfidenceLevel, TraceEvaluation
from openjarvis.learning.lifecycle.models import (
    ActorType,
    TransitionOutcome,
    TransitionRecord,
    TransitionRequest,
)
from openjarvis.learning.lifecycle.state_machine import (
    TransitionDeniedError,
    validate_transition,
)
from openjarvis.learning.store.models import (
    AuditEvent,
    AuditEventType,
    CandidateIngestOutcome,
    CandidateRevisionRecord,
    IngestDisposition,
    IngestOutcome,
    PersistedConflictLink,
    PersistedDuplicateLink,
)
from openjarvis.learning.store.sqlite import SQLiteLearningDatabase


class LearningStoreError(RuntimeError):
    """Base error for the isolated learning store."""


class LearningIntegrityError(LearningStoreError):
    """Persisted or incoming immutable content failed its hash contract."""


class IdempotencyConflictError(LearningStoreError):
    """An idempotency key was reused with different request semantics."""


class ExpectedRevisionError(LearningStoreError):
    """Compare-and-swap failed because the candidate head moved."""


class LearningRecordNotFoundError(LearningStoreError):
    """A requested learning record does not exist."""


def _json(payload: object) -> str:
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _json_time(value: datetime) -> str:
    return _iso(value).replace("+00:00", "Z")


def _validated_candidate_copy(
    current: LearningCandidate,
    **changes: object,
) -> LearningCandidate:
    values = {
        field_name: changes.get(field_name, getattr(current, field_name))
        for field_name in type(current).model_fields
        if field_name != "content_hash"
    }
    for field_name in (
        "source_evaluation_ids",
        "source_task_ids",
        "source_trace_ids",
        "source_evidence_ids",
    ):
        values[field_name] = tuple(sorted(set(values[field_name])))
    provenance = values["provenance"]
    provenance_by_key = {
        (item.source_kind.value, item.source_id, item.source_digest): item
        for item in provenance
    }
    values["provenance"] = tuple(
        provenance_by_key[key] for key in sorted(provenance_by_key)
    )
    values["confidence_basis"] = tuple(
        sorted(set(values["confidence_basis"]), key=lambda item: item.value)
    )
    groups = values["independence_groups"]
    groups_by_digest = {item.group_digest: item for item in groups}
    values["independence_groups"] = tuple(
        groups_by_digest[key] for key in sorted(groups_by_digest)
    )
    values["independence_count"] = len(values["independence_groups"])
    for field_name in ("proposed_tests", "proposed_verification"):
        values[field_name] = tuple(sorted(set(values[field_name])))
    values["quarantine_reasons"] = tuple(
        sorted(set(values["quarantine_reasons"]), key=lambda item: item.value)
    )
    draft = current.model_copy(
        update={
            **values,
            "content_hash": "0" * 64,
        }
    )
    payload = draft.model_dump(mode="python")
    payload["content_hash"] = draft.recompute_hash()
    return LearningCandidate.model_validate(payload)


def _merge_references(
    references: Iterable[MetadataReference],
) -> tuple[MetadataReference, ...]:
    by_key = {
        (item.reference_id, item.evidence_type.value, item.digest): item
        for item in references
    }
    return tuple(by_key[key] for key in sorted(by_key))


_CONFIDENCE_ORDER = {
    ConfidenceLevel.LOW: 0,
    ConfidenceLevel.MEDIUM: 1,
    ConfidenceLevel.HIGH: 2,
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SECRET_IDENTIFIER = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def _validate_public_identifier(value: str, field_name: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded identifier")
    if any(pattern.search(value) for pattern in _SECRET_IDENTIFIER):
        raise ValueError(f"{field_name} contains secret-like material")


class LearningRepository:
    """The only persistence boundary for candidate learning data."""

    def __init__(self, database: SQLiteLearningDatabase) -> None:
        self.database = database

    def initialize(self) -> tuple[int, ...]:
        return self.database.initialize()

    def persist_evaluation(
        self,
        evaluation: TraceEvaluation,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> bool:
        _validate_public_identifier(idempotency_key, "idempotency_key")
        _validate_public_identifier(correlation_id, "correlation_id")
        self._validate_evaluation(evaluation)
        request_digest = _digest(
            {
                "operation": "evaluation.ingest",
                "evaluation_id": evaluation.evaluation_id,
                "evaluation_hash": evaluation.evaluation_hash,
            }
        )
        with self.database.transaction() as connection:
            replay = self._check_idempotency(
                connection,
                idempotency_key=idempotency_key,
                operation="evaluation.ingest",
                request_digest=request_digest,
            )
            if replay is not None:
                return bool(replay["created"])
            created = self._persist_evaluation(connection, evaluation, correlation_id)
            self._complete_idempotency(
                connection,
                idempotency_key=idempotency_key,
                operation="evaluation.ingest",
                request_digest=request_digest,
                references={
                    "created": created,
                    "evaluation_id": evaluation.evaluation_id,
                },
            )
            return created

    def ingest(
        self,
        result: ExtractionResult,
        evaluations: Iterable[TraceEvaluation],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> IngestOutcome:
        _validate_public_identifier(idempotency_key, "idempotency_key")
        _validate_public_identifier(correlation_id, "correlation_id")
        ordered_evaluations = tuple(
            sorted(evaluations, key=lambda value: value.evaluation_id)
        )
        if {item.evaluation_id for item in ordered_evaluations} != set(
            result.input_evaluation_ids
        ):
            raise LearningIntegrityError(
                "ingest evaluations must exactly match extraction inputs"
            )
        for evaluation in ordered_evaluations:
            self._validate_evaluation(evaluation)
        self._validate_extraction(result)
        request_digest = _digest(
            {
                "operation": "extraction.ingest",
                "run_hash": result.run_hash,
                "evaluation_hashes": [
                    item.evaluation_hash for item in ordered_evaluations
                ],
            }
        )
        with self.database.transaction() as connection:
            replay = self._check_idempotency(
                connection,
                idempotency_key=idempotency_key,
                operation="extraction.ingest",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._outcome_from_references(replay, idempotent=True)

            existing_run = connection.execute(
                "SELECT run_hash FROM extraction_runs WHERE run_id = ?",
                (result.run_id,),
            ).fetchone()
            if existing_run is not None:
                if existing_run["run_hash"] != result.run_hash:
                    raise LearningIntegrityError(
                        "extraction run id already has a different hash"
                    )
                outcome = self._outcome_for_existing_run(connection, result)
                references = self._outcome_references(outcome)
                self._complete_idempotency(
                    connection,
                    idempotency_key=idempotency_key,
                    operation="extraction.ingest",
                    request_digest=request_digest,
                    references=references,
                )
                return outcome.model_copy(update={"idempotent": True})

            for evaluation in ordered_evaluations:
                self._persist_evaluation(connection, evaluation, correlation_id)

            connection.execute(
                """
                INSERT INTO extraction_runs(
                    run_id, run_hash, extractor_version,
                    input_evaluation_ids_json, candidate_ids_json,
                    duplicate_link_ids_json, conflict_link_ids_json,
                    warnings_json, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.run_id,
                    result.run_hash,
                    result.extractor_version,
                    _json(list(result.input_evaluation_ids)),
                    "[]",
                    "[]",
                    "[]",
                    _json(list(result.warnings)),
                    result.model_dump_json(),
                    _iso(result.created_at),
                ),
            )
            self._append_event(
                connection,
                event_type=AuditEventType.EXTRACTION_PERSISTED,
                correlation_id=correlation_id,
                reason_code="extraction_ingest",
                reference_ids=(result.run_id,),
            )

            extraction_to_stable: dict[str, str] = {}
            preliminary: list[CandidateIngestOutcome] = []
            for incoming in result.candidates:
                outcome = self._ingest_candidate(
                    connection,
                    incoming,
                    ingest_id=result.run_id,
                    correlation_id=correlation_id,
                )
                extraction_to_stable[incoming.candidate_id] = outcome.candidate_id
                preliminary.append(outcome)

            duplicate_ids = self._persist_duplicate_links(
                connection,
                result,
                extraction_to_stable,
                preliminary,
                correlation_id,
            )
            conflict_ids = self._detect_and_persist_conflicts(
                connection,
                result,
                involved_candidate_ids=set(extraction_to_stable.values()),
                correlation_id=correlation_id,
            )

            final_outcomes = tuple(
                CandidateIngestOutcome(
                    extraction_candidate_id=item.extraction_candidate_id,
                    candidate_id=item.candidate_id,
                    revision=self._head_revision(connection, item.candidate_id),
                    disposition=item.disposition,
                )
                for item in preliminary
            )
            stable_ids = tuple(item.candidate_id for item in final_outcomes)
            connection.execute(
                """
                UPDATE extraction_runs
                SET candidate_ids_json = ?, duplicate_link_ids_json = ?,
                    conflict_link_ids_json = ?
                WHERE run_id = ?
                """,
                (
                    _json(list(stable_ids)),
                    _json(list(duplicate_ids)),
                    _json(list(conflict_ids)),
                    result.run_id,
                ),
            )
            outcome = IngestOutcome(
                run_id=result.run_id,
                run_hash=result.run_hash,
                candidates=final_outcomes,
            )
            self._complete_idempotency(
                connection,
                idempotency_key=idempotency_key,
                operation="extraction.ingest",
                request_digest=request_digest,
                references=self._outcome_references(outcome),
            )
            return outcome

    def transition(self, request: TransitionRequest) -> TransitionOutcome:
        request_digest = request.semantic_digest()
        try:
            with self.database.transaction() as connection:
                replay = self._check_idempotency(
                    connection,
                    idempotency_key=request.idempotency_key,
                    operation="candidate.transition",
                    request_digest=request_digest,
                )
                if replay is not None:
                    transition = self._get_transition_with_connection(
                        connection, replay["transition_id"]
                    )
                    return TransitionOutcome(
                        transition=transition,
                        candidate_id=replay["candidate_id"],
                        revision=replay["revision"],
                        content_hash=replay["content_hash"],
                        idempotent=True,
                    )
                current = self._get_head_candidate(connection, request.candidate_id)
                if current.revision != request.expected_revision:
                    raise ExpectedRevisionError(
                        f"expected revision {request.expected_revision}, "
                        f"found {current.revision}"
                    )
                has_open_conflict = self._has_open_conflict(
                    connection, request.candidate_id
                )
                validate_transition(
                    current,
                    request,
                    has_open_conflict=has_open_conflict,
                )
                transition = self._build_transition(current, request)
                revised = self._candidate_for_transition(current, request, transition)
                revision = self._append_revision(
                    connection,
                    revised,
                    previous=current,
                    transition_id=transition.transition_id,
                )
                connection.execute(
                    """
                    INSERT INTO candidate_transition_events(
                        transition_id, candidate_id, source_revision,
                        target_revision, idempotency_key, transition_hash,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transition.transition_id,
                        transition.candidate_id,
                        transition.source_revision,
                        transition.target_revision,
                        transition.idempotency_key,
                        transition.transition_hash,
                        transition.model_dump_json(),
                        _iso(transition.created_at),
                    ),
                )
                self._compare_and_swap_head(
                    connection,
                    previous=current,
                    revised=revised,
                )
                event_type = self._transition_event_type(current.state, revised.state)
                self._append_event(
                    connection,
                    event_type=event_type,
                    candidate_id=current.candidate_id,
                    revision=revised.revision,
                    correlation_id=request.correlation_id,
                    actor_type=request.actor_type,
                    actor_id=request.actor_id,
                    reason_code=request.reason_code,
                    reference_ids=(transition.transition_id,),
                )
                outcome = TransitionOutcome(
                    transition=transition,
                    candidate_id=current.candidate_id,
                    revision=revision.revision,
                    content_hash=revision.content_hash,
                )
                self._complete_idempotency(
                    connection,
                    idempotency_key=request.idempotency_key,
                    operation="candidate.transition",
                    request_digest=request_digest,
                    references={
                        "candidate_id": outcome.candidate_id,
                        "content_hash": outcome.content_hash,
                        "revision": outcome.revision,
                        "transition_id": transition.transition_id,
                    },
                )
                return outcome
        except (TransitionDeniedError, ExpectedRevisionError) as exc:
            self._record_transition_denied(request, type(exc).__name__)
            raise

    def get_evaluation(self, evaluation_id: str) -> TraceEvaluation:
        with self.database.reader() as connection:
            row = connection.execute(
                """
                SELECT evaluation_id, input_digest, evaluation_hash, payload_json
                FROM trace_evaluations WHERE evaluation_id = ?
                """,
                (evaluation_id,),
            ).fetchone()
            if row is None:
                raise LearningRecordNotFoundError(evaluation_id)
            return self._evaluation_from_row(row)

    def evaluations_by_input_digest(
        self, input_digest: str
    ) -> tuple[TraceEvaluation, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT evaluation_id, input_digest, evaluation_hash, payload_json
                FROM trace_evaluations
                WHERE input_digest = ? ORDER BY evaluator_version, evaluation_id
                """,
                (input_digest,),
            ).fetchall()
            evaluations = tuple(self._evaluation_from_row(row) for row in rows)
            if any(item.input_digest != input_digest for item in evaluations):
                raise LearningIntegrityError("evaluation input index is inconsistent")
            return evaluations

    def get_extraction_run(self, run_id: str) -> ExtractionResult:
        with self.database.reader() as connection:
            row = connection.execute(
                """
                SELECT run_id, run_hash, payload_json
                FROM extraction_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise LearningRecordNotFoundError(run_id)
            return self._extraction_from_row(row)

    def extraction_runs_by_hash(self, run_hash: str) -> tuple[ExtractionResult, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT run_id, run_hash, payload_json FROM extraction_runs
                WHERE run_hash = ? ORDER BY run_id
                """,
                (run_hash,),
            ).fetchall()
            runs = tuple(self._extraction_from_row(row) for row in rows)
            if any(item.run_hash != run_hash for item in runs):
                raise LearningIntegrityError("extraction hash index is inconsistent")
            return runs

    def get_candidate_head(self, candidate_id: str) -> LearningCandidate:
        with self.database.reader() as connection:
            return self._get_head_candidate(connection, candidate_id)

    def get_candidate_by_duplicate_signature(
        self, duplicate_signature: str
    ) -> LearningCandidate:
        with self.database.reader() as connection:
            row = connection.execute(
                """
                SELECT candidate_id FROM candidate_heads
                WHERE duplicate_signature = ?
                """,
                (duplicate_signature,),
            ).fetchone()
            if row is None:
                raise LearningRecordNotFoundError(duplicate_signature)
            return self._get_head_candidate(connection, row["candidate_id"])

    def get_candidate_revision(
        self, candidate_id: str, revision: int
    ) -> CandidateRevisionRecord:
        with self.database.reader() as connection:
            return self._get_revision(connection, candidate_id, revision)

    def candidate_history(
        self, candidate_id: str
    ) -> tuple[CandidateRevisionRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT revision FROM candidate_revisions
                WHERE candidate_id = ? ORDER BY revision
                """,
                (candidate_id,),
            ).fetchall()
            if not rows:
                raise LearningRecordNotFoundError(candidate_id)
            return tuple(
                self._get_revision(connection, candidate_id, row["revision"])
                for row in rows
            )

    def candidates(
        self,
        *,
        state: CandidateState | None = None,
        project: str | None = None,
        scope: str | None = None,
        candidate_type: str | None = None,
    ) -> tuple[LearningCandidate, ...]:
        clauses: list[str] = []
        parameters: list[object] = []
        for column, value in (
            ("state", state.value if state else None),
            ("project", project),
            ("scope", scope),
            ("candidate_type", candidate_type),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.reader() as connection:
            query = (
                f"SELECT candidate_id FROM candidate_heads{where} ORDER BY candidate_id"
            )
            rows = connection.execute(
                query,
                tuple(parameters),
            ).fetchall()
            return tuple(
                self._get_head_candidate(connection, row["candidate_id"])
                for row in rows
            )

    def open_conflicts(self) -> tuple[PersistedConflictLink, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT conflict_id, conflict_hash, conflict_signature,
                    candidate_a_id, candidate_b_id, is_open, payload_json
                FROM candidate_conflict_links
                WHERE is_open = 1 ORDER BY conflict_id
                """
            ).fetchall()
            links = tuple(self._conflict_from_row(row) for row in rows)
            for link in links:
                signatures = tuple(
                    sorted(
                        self._get_head_candidate(
                            connection, candidate_id
                        ).duplicate_signature
                        for candidate_id in link.candidate_ids
                    )
                )
                if signatures != link.candidate_duplicate_signatures:
                    raise LearningIntegrityError(
                        "conflict candidate signatures are inconsistent"
                    )
            return links

    def duplicate_links(self) -> tuple[PersistedDuplicateLink, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT link_id, link_hash, duplicate_signature,
                    candidate_id, payload_json
                FROM candidate_duplicate_links ORDER BY link_id
                """
            ).fetchall()
            links = tuple(self._duplicate_from_row(row) for row in rows)
            for link in links:
                candidate = self._get_head_candidate(connection, link.candidate_id)
                if candidate.duplicate_signature != link.duplicate_signature:
                    raise LearningIntegrityError(
                        "duplicate link signature is inconsistent"
                    )
            return links

    def transition_history(self, candidate_id: str) -> tuple[TransitionRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT transition_id, candidate_id, source_revision,
                    target_revision, transition_hash, payload_json
                FROM candidate_transition_events
                WHERE candidate_id = ? ORDER BY target_revision
                """,
                (candidate_id,),
            ).fetchall()
            return tuple(self._transition_from_row(row) for row in rows)

    def events_after(self, sequence: int = 0) -> tuple[AuditEvent, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_id, event_hash, payload_json
                FROM learning_audit_events
                WHERE sequence > ? ORDER BY sequence
                """,
                (sequence,),
            ).fetchall()
            return tuple(self._event_from_row(row) for row in rows)

    def _persist_evaluation(
        self,
        connection: sqlite3.Connection,
        evaluation: TraceEvaluation,
        correlation_id: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT evaluation_hash FROM trace_evaluations
            WHERE evaluation_id = ?
            """,
            (evaluation.evaluation_id,),
        ).fetchone()
        if row is not None:
            if row["evaluation_hash"] != evaluation.evaluation_hash:
                raise LearningIntegrityError(
                    "evaluation id already has a different hash"
                )
            return False
        connection.execute(
            """
            INSERT INTO trace_evaluations(
                evaluation_id, input_digest, evaluator_version,
                evaluation_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation.evaluation_id,
                evaluation.input_digest,
                evaluation.evaluator_version,
                evaluation.evaluation_hash,
                evaluation.model_dump_json(),
                _iso(evaluation.created_at),
            ),
        )
        self._append_event(
            connection,
            event_type=AuditEventType.EVALUATION_PERSISTED,
            correlation_id=correlation_id,
            reason_code="evaluation_ingest",
            reference_ids=(evaluation.evaluation_id,),
        )
        return True

    def _ingest_candidate(
        self,
        connection: sqlite3.Connection,
        incoming: LearningCandidate,
        *,
        ingest_id: str,
        correlation_id: str,
    ) -> CandidateIngestOutcome:
        self._validate_candidate(incoming)
        row = connection.execute(
            """
            SELECT candidate_id FROM candidate_heads
            WHERE duplicate_signature = ?
            """,
            (incoming.duplicate_signature,),
        ).fetchone()
        if row is None:
            stable_id = f"candidate_{incoming.duplicate_signature[:32]}"
            created = _validated_candidate_copy(
                incoming,
                candidate_id=stable_id,
                revision=1,
            )
            revision = self._append_revision(
                connection,
                created,
                previous=None,
                ingest_id=ingest_id,
            )
            connection.execute(
                """
                INSERT INTO candidate_heads(
                    candidate_id, duplicate_signature, current_revision,
                    current_content_hash, state, project, scope,
                    candidate_type, proposed_destination, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_id,
                    created.duplicate_signature,
                    created.revision,
                    created.content_hash,
                    created.state.value,
                    created.project,
                    created.scope.value,
                    created.candidate_type.value,
                    created.proposed_destination.value,
                    _iso(created.updated_at),
                ),
            )
            self._append_event(
                connection,
                event_type=AuditEventType.CANDIDATE_CREATED,
                candidate_id=stable_id,
                revision=1,
                correlation_id=correlation_id,
                reason_code="candidate_ingest",
                reference_ids=(ingest_id, revision.record_hash),
            )
            return CandidateIngestOutcome(
                extraction_candidate_id=incoming.candidate_id,
                candidate_id=stable_id,
                revision=1,
                disposition=IngestDisposition.CREATED,
            )

        current = self._get_head_candidate(connection, row["candidate_id"])
        merged = self._merge_candidate(current, incoming)
        if merged.content_hash == current.content_hash:
            return CandidateIngestOutcome(
                extraction_candidate_id=incoming.candidate_id,
                candidate_id=current.candidate_id,
                revision=current.revision,
                disposition=IngestDisposition.NOOP,
            )
        revision = self._append_revision(
            connection,
            merged,
            previous=current,
            ingest_id=ingest_id,
        )
        self._compare_and_swap_head(connection, previous=current, revised=merged)
        self._append_event(
            connection,
            event_type=AuditEventType.CANDIDATE_REVISED,
            candidate_id=current.candidate_id,
            revision=merged.revision,
            correlation_id=correlation_id,
            reason_code="cross_run_evidence_merge",
            reference_ids=(ingest_id, revision.record_hash),
        )
        return CandidateIngestOutcome(
            extraction_candidate_id=incoming.candidate_id,
            candidate_id=current.candidate_id,
            revision=merged.revision,
            disposition=IngestDisposition.REVISED,
        )

    def _merge_candidate(
        self,
        current: LearningCandidate,
        incoming: LearningCandidate,
    ) -> LearningCandidate:
        if current.duplicate_signature != incoming.duplicate_signature:
            raise LearningIntegrityError("cannot merge different duplicate signatures")
        content = current.structured_content
        if isinstance(content, SuccessfulSolutionContent) and isinstance(
            incoming.structured_content, SuccessfulSolutionContent
        ):
            other = incoming.structured_content
            content = SuccessfulSolutionContent(
                task_type=content.task_type,
                verified_preconditions=_merge_references(
                    content.verified_preconditions + other.verified_preconditions
                ),
                verified_steps=_merge_references(
                    content.verified_steps + other.verified_steps
                ),
                verified_postconditions=_merge_references(
                    content.verified_postconditions + other.verified_postconditions
                ),
                allowed_scope=content.allowed_scope,
                limitations=content.limitations + other.limitations,
            )
        groups = merge_groups(
            current.independence_groups + incoming.independence_groups
        )
        if current.state is CandidateState.REJECTED:
            state = CandidateState.REJECTED
            quarantine_reasons: tuple[QuarantineReason, ...] = ()
        elif (
            current.state is CandidateState.QUARANTINED
            or incoming.state is CandidateState.QUARANTINED
        ):
            state = CandidateState.QUARANTINED
            quarantine_reasons = tuple(
                sorted(
                    set(current.quarantine_reasons + incoming.quarantine_reasons),
                    key=lambda value: value.value,
                )
            )
        else:
            state = current.state
            quarantine_reasons = ()
        confidence = max(
            (current.confidence, incoming.confidence),
            key=lambda value: _CONFIDENCE_ORDER[value],
        )
        return _validated_candidate_copy(
            current,
            revision=current.revision + 1,
            structured_content=content,
            source_evaluation_ids=(
                current.source_evaluation_ids + incoming.source_evaluation_ids
            ),
            source_task_ids=current.source_task_ids + incoming.source_task_ids,
            source_trace_ids=current.source_trace_ids + incoming.source_trace_ids,
            source_evidence_ids=(
                current.source_evidence_ids + incoming.source_evidence_ids
            ),
            provenance=current.provenance + incoming.provenance,
            confidence=confidence,
            confidence_basis=tuple(
                sorted(
                    set(current.confidence_basis + incoming.confidence_basis),
                    key=lambda value: value.value,
                )
            ),
            independence_count=len(groups),
            independence_groups=groups,
            proposed_tests=current.proposed_tests + incoming.proposed_tests,
            proposed_verification=(
                current.proposed_verification + incoming.proposed_verification
            ),
            state=state,
            quarantine_reasons=quarantine_reasons,
            updated_at=_now(),
        )

    def _append_revision(
        self,
        connection: sqlite3.Connection,
        candidate: LearningCandidate,
        *,
        previous: LearningCandidate | None,
        transition_id: str | None = None,
        ingest_id: str | None = None,
    ) -> CandidateRevisionRecord:
        created_at = _now()
        payload = {
            "candidate_id": candidate.candidate_id,
            "revision": candidate.revision,
            "previous_revision": previous.revision if previous else None,
            "previous_content_hash": previous.content_hash if previous else None,
            "candidate_payload": candidate.model_dump(mode="json"),
            "state": candidate.state.value,
            "content_hash": candidate.content_hash,
            "transition_id": transition_id,
            "ingest_id": ingest_id,
            "created_at": _json_time(created_at),
        }
        record = CandidateRevisionRecord(
            **payload,
            record_hash=_digest(payload),
        )
        connection.execute(
            """
            INSERT INTO candidate_revisions(
                candidate_id, revision, previous_revision,
                previous_content_hash, state, content_hash,
                transition_id, ingest_id, payload_json,
                record_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.candidate_id,
                record.revision,
                record.previous_revision,
                record.previous_content_hash,
                record.state.value,
                record.content_hash,
                record.transition_id,
                record.ingest_id,
                record.model_dump_json(),
                record.record_hash,
                _iso(record.created_at),
            ),
        )
        return record

    def _compare_and_swap_head(
        self,
        connection: sqlite3.Connection,
        *,
        previous: LearningCandidate,
        revised: LearningCandidate,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE candidate_heads
            SET current_revision = ?, current_content_hash = ?,
                state = ?, updated_at = ?
            WHERE candidate_id = ? AND current_revision = ?
                AND current_content_hash = ?
            """,
            (
                revised.revision,
                revised.content_hash,
                revised.state.value,
                _iso(revised.updated_at),
                previous.candidate_id,
                previous.revision,
                previous.content_hash,
            ),
        )
        if cursor.rowcount != 1:
            raise ExpectedRevisionError("candidate head compare-and-swap failed")

    def _persist_duplicate_links(
        self,
        connection: sqlite3.Connection,
        result: ExtractionResult,
        extraction_to_stable: dict[str, str],
        outcomes: list[CandidateIngestOutcome],
        correlation_id: str,
    ) -> tuple[str, ...]:
        reasons = {
            link.duplicate_signature: link.reason for link in result.duplicate_links
        }
        persisted: list[str] = []
        for outcome in outcomes:
            if outcome.disposition is IngestDisposition.CREATED and (
                next(
                    candidate.duplicate_signature
                    for candidate in result.candidates
                    if candidate.candidate_id == outcome.extraction_candidate_id
                )
                not in reasons
            ):
                continue
            incoming = next(
                candidate
                for candidate in result.candidates
                if candidate.candidate_id == outcome.extraction_candidate_id
            )
            reason = reasons.get(
                incoming.duplicate_signature,
                DuplicateReason.SAME_SEMANTIC_CONTENT,
            )
            link_seed = _digest(
                {
                    "run_id": result.run_id,
                    "duplicate_signature": incoming.duplicate_signature,
                }
            )
            payload = {
                "link_id": f"duplicate_{link_seed[:24]}",
                "duplicate_signature": incoming.duplicate_signature,
                "candidate_id": extraction_to_stable[incoming.candidate_id],
                "extraction_run_id": result.run_id,
                "source_evaluation_ids": incoming.source_evaluation_ids,
                "reason": reason,
                "created_at": _json_time(_now()),
            }
            link = PersistedDuplicateLink(
                **payload,
                link_hash=_digest(
                    {
                        **payload,
                        "reason": reason.value,
                        "source_evaluation_ids": list(
                            sorted(set(incoming.source_evaluation_ids))
                        ),
                    }
                ),
            )
            existing = connection.execute(
                """
                SELECT link_hash FROM candidate_duplicate_links
                WHERE link_id = ?
                """,
                (link.link_id,),
            ).fetchone()
            if existing is not None:
                if existing["link_hash"] != link.link_hash:
                    raise LearningIntegrityError("duplicate link id hash conflict")
                persisted.append(link.link_id)
                continue
            connection.execute(
                """
                INSERT INTO candidate_duplicate_links(
                    link_id, link_hash, duplicate_signature, candidate_id,
                    extraction_run_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.link_id,
                    link.link_hash,
                    link.duplicate_signature,
                    link.candidate_id,
                    link.extraction_run_id,
                    link.model_dump_json(),
                    _iso(link.created_at),
                ),
            )
            persisted.append(link.link_id)
            self._append_event(
                connection,
                event_type=AuditEventType.CANDIDATE_DEDUPLICATED,
                candidate_id=link.candidate_id,
                revision=self._head_revision(connection, link.candidate_id),
                correlation_id=correlation_id,
                reason_code="duplicate_signature_match",
                reference_ids=(link.link_id, result.run_id),
            )
        return tuple(sorted(persisted))

    def _detect_and_persist_conflicts(
        self,
        connection: sqlite3.Connection,
        result: ExtractionResult,
        *,
        involved_candidate_ids: set[str],
        correlation_id: str,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            "SELECT candidate_id FROM candidate_heads ORDER BY candidate_id"
        ).fetchall()
        candidates = tuple(
            self._get_head_candidate(connection, row["candidate_id"]) for row in rows
        )
        links = detect_conflicts(candidates)
        persisted: list[str] = []
        for link in links:
            if not (set(link.candidate_ids) & involved_candidate_ids):
                continue
            stored = self._persist_conflict(
                connection,
                link,
                extraction_run_id=result.run_id,
                correlation_id=correlation_id,
            )
            persisted.append(stored.conflict_id)
        return tuple(sorted(persisted))

    def _persist_conflict(
        self,
        connection: sqlite3.Connection,
        link: ConflictLink,
        *,
        extraction_run_id: str,
        correlation_id: str,
    ) -> PersistedConflictLink:
        existing = connection.execute(
            """
            SELECT payload_json FROM candidate_conflict_links
            WHERE conflict_id = ?
            """,
            (link.conflict_id,),
        ).fetchone()
        if existing is not None:
            stored = self._conflict_from_json(existing["payload_json"])
            expected_core = (
                link.conflict_type,
                link.conflict_signature,
                tuple(sorted(link.candidate_ids)),
                tuple(sorted(link.candidate_duplicate_signatures)),
                link.priority,
                link.preferred_candidate_id,
            )
            stored_core = (
                stored.conflict_type,
                stored.conflict_signature,
                stored.candidate_ids,
                stored.candidate_duplicate_signatures,
                stored.priority,
                stored.preferred_candidate_id,
            )
            if stored_core != expected_core:
                raise LearningIntegrityError("conflict id has different content")
            return stored

        for candidate_id in link.candidate_ids:
            current = self._get_head_candidate(connection, candidate_id)
            if current.state not in {
                CandidateState.QUARANTINED,
                CandidateState.REJECTED,
            }:
                reasons = tuple(
                    sorted(
                        set(
                            current.quarantine_reasons
                            + (QuarantineReason.CONFLICTING_EVIDENCE,)
                        ),
                        key=lambda value: value.value,
                    )
                )
                revised = _validated_candidate_copy(
                    current,
                    revision=current.revision + 1,
                    state=CandidateState.QUARANTINED,
                    quarantine_reasons=reasons,
                    updated_at=_now(),
                )
                self._append_revision(
                    connection,
                    revised,
                    previous=current,
                    ingest_id=extraction_run_id,
                )
                self._compare_and_swap_head(
                    connection, previous=current, revised=revised
                )
                self._append_event(
                    connection,
                    event_type=AuditEventType.CANDIDATE_QUARANTINED,
                    candidate_id=candidate_id,
                    revision=revised.revision,
                    correlation_id=correlation_id,
                    reason_code="conflict_detected",
                    reference_ids=(link.conflict_id,),
                )
        created_at = _now()
        payload = {
            "conflict_id": link.conflict_id,
            "conflict_type": link.conflict_type,
            "conflict_signature": link.conflict_signature,
            "candidate_ids": link.candidate_ids,
            "candidate_duplicate_signatures": link.candidate_duplicate_signatures,
            "priority": link.priority,
            "preferred_candidate_id": link.preferred_candidate_id,
            "reason": link.reason,
            "is_open": True,
            "extraction_run_id": extraction_run_id,
            "created_at": _json_time(created_at),
        }
        hash_payload = {
            **payload,
            "conflict_type": link.conflict_type.value,
            "candidate_ids": list(sorted(link.candidate_ids)),
            "candidate_duplicate_signatures": list(
                sorted(link.candidate_duplicate_signatures)
            ),
            "priority": link.priority.value,
        }
        stored = PersistedConflictLink(
            **payload,
            conflict_hash=_digest(hash_payload),
        )
        connection.execute(
            """
            INSERT INTO candidate_conflict_links(
                conflict_id, conflict_hash, conflict_signature,
                candidate_a_id, candidate_b_id, is_open,
                extraction_run_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stored.conflict_id,
                stored.conflict_hash,
                stored.conflict_signature,
                stored.candidate_ids[0],
                stored.candidate_ids[1],
                1,
                stored.extraction_run_id,
                stored.model_dump_json(),
                _iso(stored.created_at),
            ),
        )
        self._append_event(
            connection,
            event_type=AuditEventType.CANDIDATE_CONFLICT_DETECTED,
            correlation_id=correlation_id,
            reason_code="conflict_signature_match",
            reference_ids=(stored.conflict_id,) + stored.candidate_ids,
        )
        return stored

    def _build_transition(
        self,
        current: LearningCandidate,
        request: TransitionRequest,
    ) -> TransitionRecord:
        transition_id = f"transition_{uuid.uuid4().hex}"
        created_at = _now()
        payload = {
            "transition_id": transition_id,
            "candidate_id": current.candidate_id,
            "expected_revision": request.expected_revision,
            "source_revision": current.revision,
            "target_revision": current.revision + 1,
            "from_state": current.state,
            "to_state": request.target_state,
            "actor_type": request.actor_type,
            "actor_id": request.actor_id,
            "reason": request.reason,
            "reason_code": request.reason_code,
            "correlation_id": request.correlation_id,
            "idempotency_key": request.idempotency_key,
            "quarantine_resolution_ids": tuple(
                item.resolution_id for item in request.quarantine_resolution_records
            ),
            "created_at": _json_time(created_at),
        }
        semantic = {
            **payload,
            "from_state": current.state.value,
            "to_state": request.target_state.value,
            "actor_type": request.actor_type.value,
            "quarantine_resolution_ids": list(
                sorted(payload["quarantine_resolution_ids"])
            ),
        }
        return TransitionRecord(
            **payload,
            transition_hash=_digest(semantic),
        )

    def _candidate_for_transition(
        self,
        current: LearningCandidate,
        request: TransitionRequest,
        transition: TransitionRecord,
    ) -> LearningCandidate:
        if request.target_state is CandidateState.QUARANTINED:
            quarantine_reasons = request.quarantine_reasons
        else:
            quarantine_reasons = ()
        rejection_reason = (
            request.reason if request.target_state is CandidateState.REJECTED else None
        )
        return _validated_candidate_copy(
            current,
            revision=transition.target_revision,
            state=request.target_state,
            quarantine_reasons=quarantine_reasons,
            rejection_reason=rejection_reason,
            updated_at=transition.created_at,
        )

    def _get_head_candidate(
        self, connection: sqlite3.Connection, candidate_id: str
    ) -> LearningCandidate:
        row = connection.execute(
            """
            SELECT current_revision, current_content_hash, state,
                duplicate_signature
            FROM candidate_heads WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError(candidate_id)
        revision = self._get_revision(connection, candidate_id, row["current_revision"])
        candidate = revision.candidate_payload
        if (
            candidate.content_hash != row["current_content_hash"]
            or candidate.state.value != row["state"]
            or candidate.duplicate_signature != row["duplicate_signature"]
        ):
            raise LearningIntegrityError("candidate head projection is inconsistent")
        return candidate

    def _get_revision(
        self,
        connection: sqlite3.Connection,
        candidate_id: str,
        revision: int,
    ) -> CandidateRevisionRecord:
        row = connection.execute(
            """
            SELECT candidate_id, revision, previous_revision,
                previous_content_hash, state, content_hash,
                transition_id, ingest_id, record_hash, payload_json
            FROM candidate_revisions
            WHERE candidate_id = ? AND revision = ?
            """,
            (candidate_id, revision),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError(f"{candidate_id}:{revision}")
        try:
            record = CandidateRevisionRecord.model_validate_json(row["payload_json"])
        except ValueError as exc:
            raise LearningIntegrityError(
                "candidate revision integrity failure"
            ) from exc
        indexed = (
            row["candidate_id"],
            row["revision"],
            row["previous_revision"],
            row["previous_content_hash"],
            row["state"],
            row["content_hash"],
            row["transition_id"],
            row["ingest_id"],
            row["record_hash"],
        )
        payload_values = (
            record.candidate_id,
            record.revision,
            record.previous_revision,
            record.previous_content_hash,
            record.state.value,
            record.content_hash,
            record.transition_id,
            record.ingest_id,
            record.record_hash,
        )
        if indexed != payload_values:
            raise LearningIntegrityError("candidate revision index is inconsistent")
        if record.revision > 1:
            parent = connection.execute(
                """
                SELECT content_hash FROM candidate_revisions
                WHERE candidate_id = ? AND revision = ?
                """,
                (candidate_id, record.previous_revision),
            ).fetchone()
            if parent is None:
                raise LearningIntegrityError("candidate revision parent is missing")
            if parent["content_hash"] != record.previous_content_hash:
                raise LearningIntegrityError("candidate revision parent hash mismatch")
        if record.transition_id is not None:
            transition_row = connection.execute(
                """
                SELECT transition_id, candidate_id, source_revision,
                    target_revision, transition_hash, payload_json
                FROM candidate_transition_events
                WHERE transition_id = ?
                """,
                (record.transition_id,),
            ).fetchone()
            if transition_row is None:
                raise LearningIntegrityError(
                    "candidate review revision transition is missing"
                )
            transition = self._transition_from_row(transition_row)
            if (
                transition.candidate_id != record.candidate_id
                or transition.target_revision != record.revision
            ):
                raise LearningIntegrityError(
                    "candidate review revision transition is inconsistent"
                )
        if record.ingest_id is not None:
            ingest_row = connection.execute(
                "SELECT run_hash FROM extraction_runs WHERE run_id = ?",
                (record.ingest_id,),
            ).fetchone()
            if ingest_row is None:
                raise LearningIntegrityError(
                    "candidate ingest revision extraction run is missing"
                )
        return record

    def _head_revision(self, connection: sqlite3.Connection, candidate_id: str) -> int:
        row = connection.execute(
            "SELECT current_revision FROM candidate_heads WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError(candidate_id)
        return int(row["current_revision"])

    def _has_open_conflict(
        self, connection: sqlite3.Connection, candidate_id: str
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1 FROM candidate_conflict_links
            WHERE is_open = 1 AND (candidate_a_id = ? OR candidate_b_id = ?)
            LIMIT 1
            """,
            (candidate_id, candidate_id),
        ).fetchone()
        return row is not None

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: AuditEventType,
        correlation_id: str,
        reason_code: str,
        reference_ids: tuple[str, ...],
        candidate_id: str | None = None,
        revision: int | None = None,
        actor_type: ActorType | None = None,
        actor_id: str | None = None,
    ) -> AuditEvent:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM learning_audit_events"
        ).fetchone()
        sequence = int(row["next"])
        event_id = f"event_{uuid.uuid4().hex}"
        timestamp = _now()
        payload = {
            "event_id": event_id,
            "sequence": sequence,
            "event_type": event_type,
            "candidate_id": candidate_id,
            "revision": revision,
            "correlation_id": correlation_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "reason_code": reason_code,
            "reference_ids": tuple(sorted(set(reference_ids))),
            "timestamp": _json_time(timestamp),
        }
        semantic = {
            **payload,
            "event_type": event_type.value,
            "actor_type": actor_type.value if actor_type else None,
            "reference_ids": list(payload["reference_ids"]),
        }
        event = AuditEvent(**payload, event_hash=_digest(semantic))
        connection.execute(
            """
            INSERT INTO learning_audit_events(
                sequence, event_id, event_type, candidate_id, revision,
                correlation_id, actor_type, actor_id, reason_code,
                reference_ids_json, timestamp, event_hash, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.sequence,
                event.event_id,
                event.event_type.value,
                event.candidate_id,
                event.revision,
                event.correlation_id,
                event.actor_type.value if event.actor_type else None,
                event.actor_id,
                event.reason_code,
                _json(list(event.reference_ids)),
                _iso(event.timestamp),
                event.event_hash,
                event.model_dump_json(),
            ),
        )
        return event

    def _record_transition_denied(
        self, request: TransitionRequest, reason_code: str
    ) -> None:
        try:
            with self.database.transaction() as connection:
                self._append_event(
                    connection,
                    event_type=AuditEventType.LIFECYCLE_TRANSITION_DENIED,
                    candidate_id=request.candidate_id,
                    revision=request.expected_revision,
                    correlation_id=request.correlation_id,
                    actor_type=request.actor_type,
                    actor_id=request.actor_id,
                    reason_code=reason_code,
                    reference_ids=(request.idempotency_key,),
                )
        except sqlite3.Error:
            return

    def _check_idempotency(
        self,
        connection: sqlite3.Connection,
        *,
        idempotency_key: str,
        operation: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT operation, request_digest, status, result_references_json
            FROM learning_idempotency_records WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation or row["request_digest"] != request_digest:
            raise IdempotencyConflictError(
                "idempotency key was reused with different request semantics"
            )
        if row["status"] != "completed":
            raise LearningIntegrityError("incomplete idempotency record persisted")
        return json.loads(row["result_references_json"])

    def _complete_idempotency(
        self,
        connection: sqlite3.Connection,
        *,
        idempotency_key: str,
        operation: str,
        request_digest: str,
        references: dict[str, object],
    ) -> None:
        timestamp = _iso(_now())
        connection.execute(
            """
            INSERT INTO learning_idempotency_records(
                idempotency_key, operation, request_digest, status,
                result_references_json, created_at, completed_at
            ) VALUES (?, ?, ?, 'completed', ?, ?, ?)
            """,
            (
                idempotency_key,
                operation,
                request_digest,
                _json(references),
                timestamp,
                timestamp,
            ),
        )

    def _outcome_references(self, outcome: IngestOutcome) -> dict[str, object]:
        return {
            "run_id": outcome.run_id,
            "run_hash": outcome.run_hash,
            "candidates": [item.model_dump(mode="json") for item in outcome.candidates],
        }

    def _outcome_from_references(
        self, references: dict[str, Any], *, idempotent: bool
    ) -> IngestOutcome:
        return IngestOutcome(
            run_id=references["run_id"],
            run_hash=references["run_hash"],
            candidates=tuple(
                CandidateIngestOutcome.model_validate(item)
                for item in references["candidates"]
            ),
            idempotent=idempotent,
        )

    def _outcome_for_existing_run(
        self,
        connection: sqlite3.Connection,
        result: ExtractionResult,
    ) -> IngestOutcome:
        row = connection.execute(
            "SELECT candidate_ids_json FROM extraction_runs WHERE run_id = ?",
            (result.run_id,),
        ).fetchone()
        candidate_ids = json.loads(row["candidate_ids_json"])
        outcomes = tuple(
            CandidateIngestOutcome(
                extraction_candidate_id=incoming.candidate_id,
                candidate_id=candidate_id,
                revision=self._head_revision(connection, candidate_id),
                disposition=IngestDisposition.NOOP,
            )
            for incoming, candidate_id in zip(
                result.candidates, candidate_ids, strict=True
            )
        )
        return IngestOutcome(
            run_id=result.run_id,
            run_hash=result.run_hash,
            candidates=outcomes,
            idempotent=True,
        )

    def _get_transition_with_connection(
        self, connection: sqlite3.Connection, transition_id: str
    ) -> TransitionRecord:
        row = connection.execute(
            """
            SELECT transition_id, candidate_id, source_revision,
                target_revision, transition_hash, payload_json
            FROM candidate_transition_events
            WHERE transition_id = ?
            """,
            (transition_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError(transition_id)
        return self._transition_from_row(row)

    def _transition_event_type(
        self, from_state: CandidateState, to_state: CandidateState
    ) -> AuditEventType:
        if to_state is CandidateState.UNDER_REVIEW:
            if from_state is CandidateState.QUARANTINED:
                return AuditEventType.CANDIDATE_QUARANTINE_RESOLVED
            return AuditEventType.CANDIDATE_REVIEW_STARTED
        if to_state is CandidateState.REJECTED:
            return AuditEventType.CANDIDATE_REJECTED
        return AuditEventType.CANDIDATE_QUARANTINED

    def _validate_evaluation(self, evaluation: TraceEvaluation) -> None:
        if evaluation.recompute_hash() != evaluation.evaluation_hash:
            raise LearningIntegrityError("evaluation hash mismatch")

    def _validate_extraction(self, result: ExtractionResult) -> None:
        if result.recompute_hash() != result.run_hash:
            raise LearningIntegrityError("extraction run hash mismatch")
        for candidate in result.candidates:
            self._validate_candidate(candidate)

    def _validate_candidate(self, candidate: LearningCandidate) -> None:
        if candidate.recompute_hash() != candidate.content_hash:
            raise LearningIntegrityError("candidate content hash mismatch")

    def _evaluation_from_json(self, payload: str) -> TraceEvaluation:
        try:
            evaluation = TraceEvaluation.model_validate_json(payload)
        except ValueError as exc:
            raise LearningIntegrityError("evaluation integrity failure") from exc
        self._validate_evaluation(evaluation)
        return evaluation

    def _evaluation_from_row(self, row: sqlite3.Row) -> TraceEvaluation:
        evaluation = self._evaluation_from_json(row["payload_json"])
        if (
            evaluation.evaluation_id != row["evaluation_id"]
            or evaluation.input_digest != row["input_digest"]
            or evaluation.evaluation_hash != row["evaluation_hash"]
        ):
            raise LearningIntegrityError("evaluation index is inconsistent")
        return evaluation

    def _extraction_from_json(self, payload: str) -> ExtractionResult:
        try:
            result = ExtractionResult.model_validate_json(payload)
        except ValueError as exc:
            raise LearningIntegrityError("extraction integrity failure") from exc
        self._validate_extraction(result)
        return result

    def _extraction_from_row(self, row: sqlite3.Row) -> ExtractionResult:
        result = self._extraction_from_json(row["payload_json"])
        if result.run_id != row["run_id"] or result.run_hash != row["run_hash"]:
            raise LearningIntegrityError("extraction index is inconsistent")
        return result

    def _transition_from_json(self, payload: str) -> TransitionRecord:
        try:
            return TransitionRecord.model_validate_json(payload)
        except ValueError as exc:
            raise LearningIntegrityError("transition integrity failure") from exc

    def _transition_from_row(self, row: sqlite3.Row) -> TransitionRecord:
        transition = self._transition_from_json(row["payload_json"])
        if (
            transition.transition_id != row["transition_id"]
            or transition.candidate_id != row["candidate_id"]
            or transition.source_revision != row["source_revision"]
            or transition.target_revision != row["target_revision"]
            or transition.transition_hash != row["transition_hash"]
        ):
            raise LearningIntegrityError("transition index is inconsistent")
        return transition

    def _event_from_json(self, payload: str) -> AuditEvent:
        try:
            return AuditEvent.model_validate_json(payload)
        except ValueError as exc:
            raise LearningIntegrityError("audit event integrity failure") from exc

    def _event_from_row(self, row: sqlite3.Row) -> AuditEvent:
        event = self._event_from_json(row["payload_json"])
        if (
            event.sequence != row["sequence"]
            or event.event_id != row["event_id"]
            or event.event_hash != row["event_hash"]
        ):
            raise LearningIntegrityError("audit event index is inconsistent")
        return event

    def _duplicate_from_json(self, payload: str) -> PersistedDuplicateLink:
        try:
            return PersistedDuplicateLink.model_validate_json(payload)
        except ValueError as exc:
            raise LearningIntegrityError("duplicate link integrity failure") from exc

    def _duplicate_from_row(self, row: sqlite3.Row) -> PersistedDuplicateLink:
        link = self._duplicate_from_json(row["payload_json"])
        if (
            link.link_id != row["link_id"]
            or link.link_hash != row["link_hash"]
            or link.duplicate_signature != row["duplicate_signature"]
            or link.candidate_id != row["candidate_id"]
        ):
            raise LearningIntegrityError("duplicate link index is inconsistent")
        return link

    def _conflict_from_json(self, payload: str) -> PersistedConflictLink:
        try:
            return PersistedConflictLink.model_validate_json(payload)
        except ValueError as exc:
            raise LearningIntegrityError("conflict link integrity failure") from exc

    def _conflict_from_row(self, row: sqlite3.Row) -> PersistedConflictLink:
        link = self._conflict_from_json(row["payload_json"])
        indexed_ids = tuple(sorted((row["candidate_a_id"], row["candidate_b_id"])))
        if (
            link.conflict_id != row["conflict_id"]
            or link.conflict_hash != row["conflict_hash"]
            or link.conflict_signature != row["conflict_signature"]
            or link.candidate_ids != indexed_ids
            or link.is_open is not bool(row["is_open"])
        ):
            raise LearningIntegrityError("conflict link index is inconsistent")
        return link


__all__ = [
    "ExpectedRevisionError",
    "IdempotencyConflictError",
    "LearningIntegrityError",
    "LearningRecordNotFoundError",
    "LearningRepository",
    "LearningStoreError",
]
