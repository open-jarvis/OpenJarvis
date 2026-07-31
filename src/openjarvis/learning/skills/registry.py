"""Persistent, append-only and integrity-checked skill registry."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from packaging.version import Version

from openjarvis.learning.candidates.models import CandidateState, CandidateType
from openjarvis.learning.lifecycle.models import ActorType
from openjarvis.learning.skills.manifest import (
    SkillLifecycleStatus,
    SkillManifest,
)
from openjarvis.learning.skills.registry_models import (
    RegistryDisposition,
    SkillAuditEvent,
    SkillAuditEventType,
    SkillRegistrationOutcome,
    SkillVersionHead,
    SkillVersionRecord,
)
from openjarvis.learning.store.repository import (
    IdempotencyConflictError,
    LearningIntegrityError,
    LearningRecordNotFoundError,
    LearningRepository,
    LearningStoreError,
)
from openjarvis.learning.store.sqlite import SQLiteLearningDatabase
from openjarvis.tools.manifest import ToolManifestCatalog

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SECRET_IDENTIFIER = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


class SkillRegistryError(LearningStoreError):
    """A skill registry operation violated a lifecycle contract."""


class SkillVersionConflictError(SkillRegistryError):
    """A semantic version or registry revision conflicted."""


def _json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _json_time(value: datetime) -> str:
    return _iso(value).replace("+00:00", "Z")


def _validate_identifier(value: str, field_name: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded identifier")
    if any(pattern.search(value) for pattern in _SECRET_IDENTIFIER):
        raise ValueError(f"{field_name} contains secret-like material")


class SkillRegistry:
    """The only persistence boundary for trusted skill manifests and versions."""

    def __init__(
        self,
        database: SQLiteLearningDatabase,
        *,
        learning: LearningRepository,
        tool_catalog: ToolManifestCatalog,
    ) -> None:
        if learning.database.path != database.path:
            raise ValueError("learning repository and skill registry must share a DB")
        self.database = database
        self.learning = learning
        self.tool_catalog = tool_catalog

    def initialize(self) -> tuple[int, ...]:
        return self.database.initialize()

    def register_manifest(
        self,
        manifest: SkillManifest,
        *,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> SkillRegistrationOutcome:
        for value, field_name in (
            (actor_id, "actor_id"),
            (reason_code, "reason_code"),
            (correlation_id, "correlation_id"),
            (idempotency_key, "idempotency_key"),
        ):
            _validate_identifier(value, field_name)
        if actor_type not in {
            ActorType.USER,
            ActorType.SYSTEM_POLICY,
            ActorType.DETERMINISTIC_TEST,
        }:
            raise SkillRegistryError("untrusted actor type")
        if manifest.status not in {
            SkillLifecycleStatus.DRAFT,
            SkillLifecycleStatus.QUARANTINED,
        }:
            raise SkillRegistryError("only draft or quarantined manifests register")
        manifest.validate_tool_bindings(self.tool_catalog)
        request_digest = _digest(
            {
                "operation": "skill.version.register",
                "skill_id": manifest.skill_id,
                "semantic_version": manifest.semantic_version,
                "manifest_hash": manifest.content_hash,
                "candidate_id": manifest.origin_candidate_id,
                "candidate_revision": manifest.origin_candidate_revision,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "reason_code": reason_code,
                "correlation_id": correlation_id,
            }
        )
        with self.database.transaction() as connection:
            replay = self._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.version.register",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._registration_outcome(
                    connection,
                    replay["skill_id"],
                    replay["semantic_version"],
                    RegistryDisposition.REPLAYED,
                )
            self._validate_candidate_binding(connection, manifest)
            existing = connection.execute(
                """
                SELECT manifest_hash FROM skill_versions
                WHERE skill_id = ? AND semantic_version = ?
                """,
                (manifest.skill_id, manifest.semantic_version),
            ).fetchone()
            if existing is not None:
                if existing["manifest_hash"] != manifest.content_hash:
                    raise SkillVersionConflictError(
                        "semantic version already has different content"
                    )
                outcome = self._registration_outcome(
                    connection,
                    manifest.skill_id,
                    manifest.semantic_version,
                    RegistryDisposition.REPLAYED,
                )
                self._complete_idempotency(
                    connection,
                    key=idempotency_key,
                    operation="skill.version.register",
                    request_digest=request_digest,
                    references={
                        "skill_id": manifest.skill_id,
                        "semantic_version": manifest.semantic_version,
                    },
                )
                return outcome

            latest = connection.execute(
                """
                SELECT semantic_version, registry_revision
                FROM skill_versions
                WHERE skill_id = ?
                ORDER BY registry_revision DESC LIMIT 1
                """,
                (manifest.skill_id,),
            ).fetchone()
            registry_revision = 1
            if latest is None:
                if manifest.supersedes_version is not None:
                    raise SkillVersionConflictError(
                        "first skill version cannot supersede another version"
                    )
            else:
                registry_revision = int(latest["registry_revision"]) + 1
                if manifest.supersedes_version != latest["semantic_version"]:
                    raise SkillVersionConflictError(
                        "new version must supersede the latest registry version"
                    )
                if Version(manifest.semantic_version) <= Version(
                    latest["semantic_version"]
                ):
                    raise SkillVersionConflictError(
                        "semantic version must increase monotonically"
                    )
            existing_candidate_skill = connection.execute(
                """
                SELECT skill_id FROM skill_candidate_links
                WHERE candidate_id = ? ORDER BY created_at LIMIT 1
                """,
                (manifest.origin_candidate_id,),
            ).fetchone()
            if (
                existing_candidate_skill is not None
                and existing_candidate_skill["skill_id"] != manifest.skill_id
            ):
                raise SkillVersionConflictError(
                    "candidate is already bound to another stable skill ID"
                )

            created_at = manifest.created_at
            version = self._build_version_record(
                manifest,
                registry_revision=registry_revision,
                created_at=created_at,
            )
            connection.execute(
                """
                INSERT INTO skill_manifests(
                    content_hash, skill_id, semantic_version, candidate_id,
                    candidate_revision, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.content_hash,
                    manifest.skill_id,
                    manifest.semantic_version,
                    manifest.origin_candidate_id,
                    manifest.origin_candidate_revision,
                    _json(manifest.model_dump(mode="json")),
                    _iso(created_at),
                ),
            )
            connection.execute(
                """
                INSERT INTO skill_versions(
                    skill_id, semantic_version, registry_revision, manifest_hash,
                    candidate_id, candidate_revision, supersedes_version,
                    record_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version.skill_id,
                    version.semantic_version,
                    version.registry_revision,
                    version.manifest_hash,
                    version.candidate_id,
                    version.candidate_revision,
                    version.supersedes_version,
                    version.record_hash,
                    _json(version.model_dump(mode="json")),
                    _iso(version.created_at),
                ),
            )
            head = SkillVersionHead(
                skill_id=manifest.skill_id,
                semantic_version=manifest.semantic_version,
                lifecycle_state=manifest.status,
                state_revision=1,
                manifest_hash=manifest.content_hash,
                candidate_id=manifest.origin_candidate_id,
                candidate_revision=manifest.origin_candidate_revision,
                updated_at=created_at,
            )
            connection.execute(
                """
                INSERT INTO skill_version_heads(
                    skill_id, semantic_version, lifecycle_state, state_revision,
                    manifest_hash, candidate_id, candidate_revision, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    head.skill_id,
                    head.semantic_version,
                    head.lifecycle_state.value,
                    head.state_revision,
                    head.manifest_hash,
                    head.candidate_id,
                    head.candidate_revision,
                    _iso(head.updated_at),
                ),
            )
            link_payload = {
                "link_id": f"skill_link_{uuid.uuid4().hex}",
                "skill_id": manifest.skill_id,
                "semantic_version": manifest.semantic_version,
                "candidate_id": manifest.origin_candidate_id,
                "candidate_revision": manifest.origin_candidate_revision,
                "manifest_hash": manifest.content_hash,
                "created_at": _json_time(created_at),
            }
            link_hash = _digest(link_payload)
            connection.execute(
                """
                INSERT INTO skill_candidate_links(
                    link_id, skill_id, semantic_version, candidate_id,
                    candidate_revision, manifest_hash, link_hash,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link_payload["link_id"],
                    manifest.skill_id,
                    manifest.semantic_version,
                    manifest.origin_candidate_id,
                    manifest.origin_candidate_revision,
                    manifest.content_hash,
                    link_hash,
                    _json({**link_payload, "link_hash": link_hash}),
                    _iso(created_at),
                ),
            )
            for event_type in (
                SkillAuditEventType.MANIFEST_CREATED,
                SkillAuditEventType.VERSION_REGISTERED,
            ):
                self._append_event(
                    connection,
                    event_type=event_type,
                    skill_id=manifest.skill_id,
                    semantic_version=manifest.semantic_version,
                    candidate_id=manifest.origin_candidate_id,
                    candidate_revision=manifest.origin_candidate_revision,
                    correlation_id=correlation_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason_code=reason_code,
                    reference_ids=(manifest.content_hash, link_payload["link_id"]),
                    created_at=created_at,
                )
            self._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.version.register",
                request_digest=request_digest,
                references={
                    "skill_id": manifest.skill_id,
                    "semantic_version": manifest.semantic_version,
                },
            )
            return SkillRegistrationOutcome(
                manifest=manifest,
                version=version,
                head=head,
                disposition=RegistryDisposition.CREATED,
            )

    def get_manifest(self, skill_id: str, semantic_version: str) -> SkillManifest:
        with self.database.reader() as connection:
            return self._manifest(connection, skill_id, semantic_version)

    def get_version(self, skill_id: str, semantic_version: str) -> SkillVersionRecord:
        with self.database.reader() as connection:
            return self._version(connection, skill_id, semantic_version)

    def get_head(self, skill_id: str, semantic_version: str) -> SkillVersionHead:
        with self.database.reader() as connection:
            return self._head(connection, skill_id, semantic_version)

    def versions(self, skill_id: str) -> tuple[SkillVersionRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT semantic_version FROM skill_versions
                WHERE skill_id = ? ORDER BY registry_revision
                """,
                (skill_id,),
            ).fetchall()
            return tuple(
                self._version(connection, skill_id, row["semantic_version"])
                for row in rows
            )

    def events_after(self, sequence: int = 0) -> tuple[SkillAuditEvent, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json, event_hash, event_id, sequence, event_type,
                       skill_id, semantic_version, candidate_id,
                       candidate_revision, task_id, session_id, correlation_id,
                       actor_type, actor_id, reason_code, reference_ids_json,
                       created_at
                FROM skill_audit_events WHERE sequence > ? ORDER BY sequence
                """,
                (sequence,),
            ).fetchall()
            return tuple(self._event_from_row(row) for row in rows)

    def _validate_candidate_binding(
        self, connection: sqlite3.Connection, manifest: SkillManifest
    ) -> None:
        row = connection.execute(
            """
            SELECT current_revision, current_content_hash, state, candidate_type
            FROM candidate_heads WHERE candidate_id = ?
            """,
            (manifest.origin_candidate_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("origin candidate does not exist")
        if int(row["current_revision"]) != manifest.origin_candidate_revision:
            raise SkillVersionConflictError("origin candidate revision is stale")
        if row["candidate_type"] != CandidateType.SKILL.value:
            raise SkillRegistryError("only skill candidates may create manifests")
        if row["state"] != CandidateState.UNDER_REVIEW.value:
            raise SkillRegistryError("skill manifest draft requires under_review")
        revision = self.learning.get_candidate_revision(
            manifest.origin_candidate_id,
            manifest.origin_candidate_revision,
        )
        if revision.content_hash != row["current_content_hash"]:
            raise LearningIntegrityError("candidate head content hash mismatch")

    @staticmethod
    def _build_version_record(
        manifest: SkillManifest,
        *,
        registry_revision: int,
        created_at: datetime,
    ) -> SkillVersionRecord:
        payload = {
            "skill_id": manifest.skill_id,
            "semantic_version": manifest.semantic_version,
            "registry_revision": registry_revision,
            "manifest_hash": manifest.content_hash,
            "candidate_id": manifest.origin_candidate_id,
            "candidate_revision": manifest.origin_candidate_revision,
            "supersedes_version": manifest.supersedes_version,
            "created_at": _json_time(created_at),
        }
        return SkillVersionRecord(**payload, record_hash=_digest(payload))

    def _manifest(
        self, connection: sqlite3.Connection, skill_id: str, semantic_version: str
    ) -> SkillManifest:
        row = connection.execute(
            """
            SELECT content_hash, skill_id, semantic_version, candidate_id,
                   candidate_revision, payload_json, created_at
            FROM skill_manifests WHERE skill_id = ? AND semantic_version = ?
            """,
            (skill_id, semantic_version),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("skill manifest not found")
        try:
            manifest = SkillManifest.model_validate(json.loads(row["payload_json"]))
        except Exception as exc:
            raise LearningIntegrityError("skill manifest integrity failure") from exc
        if (
            manifest.content_hash != row["content_hash"]
            or manifest.skill_id != row["skill_id"]
            or manifest.semantic_version != row["semantic_version"]
            or manifest.origin_candidate_id != row["candidate_id"]
            or manifest.origin_candidate_revision != int(row["candidate_revision"])
            or _iso(manifest.created_at) != row["created_at"]
        ):
            raise LearningIntegrityError("skill manifest index integrity failure")
        return manifest

    def _version(
        self, connection: sqlite3.Connection, skill_id: str, semantic_version: str
    ) -> SkillVersionRecord:
        row = connection.execute(
            """
            SELECT skill_id, semantic_version, registry_revision, manifest_hash,
                   candidate_id, candidate_revision, supersedes_version,
                   record_hash, payload_json, created_at
            FROM skill_versions WHERE skill_id = ? AND semantic_version = ?
            """,
            (skill_id, semantic_version),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("skill version not found")
        try:
            version = SkillVersionRecord.model_validate(json.loads(row["payload_json"]))
        except Exception as exc:
            raise LearningIntegrityError("skill version integrity failure") from exc
        columns = {
            "skill_id": row["skill_id"],
            "semantic_version": row["semantic_version"],
            "registry_revision": int(row["registry_revision"]),
            "manifest_hash": row["manifest_hash"],
            "candidate_id": row["candidate_id"],
            "candidate_revision": int(row["candidate_revision"]),
            "supersedes_version": row["supersedes_version"],
            "record_hash": row["record_hash"],
            "created_at": row["created_at"],
        }
        expected = version.model_dump(mode="json")
        expected["created_at"] = _iso(version.created_at)
        if columns != expected:
            raise LearningIntegrityError("skill version index integrity failure")
        manifest = self._manifest(connection, skill_id, semantic_version)
        if manifest.content_hash != version.manifest_hash:
            raise LearningIntegrityError("skill version manifest reference mismatch")
        return version

    def _head(
        self, connection: sqlite3.Connection, skill_id: str, semantic_version: str
    ) -> SkillVersionHead:
        row = connection.execute(
            """
            SELECT skill_id, semantic_version, lifecycle_state, state_revision,
                   manifest_hash, candidate_id, candidate_revision, updated_at
            FROM skill_version_heads WHERE skill_id = ? AND semantic_version = ?
            """,
            (skill_id, semantic_version),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("skill version head not found")
        try:
            head = SkillVersionHead(
                skill_id=row["skill_id"],
                semantic_version=row["semantic_version"],
                lifecycle_state=row["lifecycle_state"],
                state_revision=int(row["state_revision"]),
                manifest_hash=row["manifest_hash"],
                candidate_id=row["candidate_id"],
                candidate_revision=int(row["candidate_revision"]),
                updated_at=row["updated_at"],
            )
        except Exception as exc:
            raise LearningIntegrityError("skill head integrity failure") from exc
        version = self._version(connection, skill_id, semantic_version)
        if (
            head.manifest_hash != version.manifest_hash
            or head.candidate_id != version.candidate_id
        ):
            raise LearningIntegrityError("skill head reference integrity failure")
        return head

    def _registration_outcome(
        self,
        connection: sqlite3.Connection,
        skill_id: str,
        semantic_version: str,
        disposition: RegistryDisposition,
    ) -> SkillRegistrationOutcome:
        return SkillRegistrationOutcome(
            manifest=self._manifest(connection, skill_id, semantic_version),
            version=self._version(connection, skill_id, semantic_version),
            head=self._head(connection, skill_id, semantic_version),
            disposition=disposition,
        )

    def _check_idempotency(
        self,
        connection: sqlite3.Connection,
        *,
        key: str,
        operation: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT operation, request_digest, status, result_references_json
            FROM skill_idempotency_records WHERE idempotency_key = ?
            """,
            (key,),
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation or row["request_digest"] != request_digest:
            raise IdempotencyConflictError(
                "idempotency key was reused with different request semantics"
            )
        if row["status"] != "completed":
            raise LearningIntegrityError("incomplete skill idempotency record")
        return json.loads(row["result_references_json"])

    @staticmethod
    def _complete_idempotency(
        connection: sqlite3.Connection,
        *,
        key: str,
        operation: str,
        request_digest: str,
        references: dict[str, Any],
    ) -> None:
        now = _iso(_now())
        connection.execute(
            """
            INSERT INTO skill_idempotency_records(
                idempotency_key, operation, request_digest, status,
                result_references_json, created_at, completed_at
            ) VALUES (?, ?, ?, 'completed', ?, ?, ?)
            """,
            (key, operation, request_digest, _json(references), now, now),
        )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        *,
        event_type: SkillAuditEventType,
        skill_id: str,
        semantic_version: str,
        candidate_id: str,
        candidate_revision: int,
        correlation_id: str,
        actor_type: ActorType,
        actor_id: str,
        reason_code: str,
        reference_ids: tuple[str, ...],
        created_at: datetime,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> SkillAuditEvent:
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM skill_audit_events"
            ).fetchone()[0]
        )
        payload = {
            "event_id": f"skill_event_{uuid.uuid4().hex}",
            "sequence": sequence,
            "event_type": event_type.value,
            "skill_id": skill_id,
            "semantic_version": semantic_version,
            "candidate_id": candidate_id,
            "candidate_revision": candidate_revision,
            "task_id": task_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "actor_type": actor_type.value,
            "actor_id": actor_id,
            "reason_code": reason_code,
            "reference_ids": sorted(set(reference_ids)),
            "created_at": _json_time(created_at),
        }
        event = SkillAuditEvent(**payload, event_hash=_digest(payload))
        connection.execute(
            """
            INSERT INTO skill_audit_events(
                sequence, event_id, event_type, skill_id, semantic_version,
                candidate_id, candidate_revision, task_id, session_id,
                correlation_id, actor_type, actor_id, reason_code,
                reference_ids_json, event_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.sequence,
                event.event_id,
                event.event_type.value,
                event.skill_id,
                event.semantic_version,
                event.candidate_id,
                event.candidate_revision,
                event.task_id,
                event.session_id,
                event.correlation_id,
                event.actor_type.value if event.actor_type else None,
                event.actor_id,
                event.reason_code,
                _json(list(event.reference_ids)),
                event.event_hash,
                _json(event.model_dump(mode="json")),
                _iso(event.created_at),
            ),
        )
        return event

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> SkillAuditEvent:
        try:
            event = SkillAuditEvent.model_validate(json.loads(row["payload_json"]))
        except Exception as exc:
            raise LearningIntegrityError("skill event integrity failure") from exc
        columns = {
            "event_id": row["event_id"],
            "sequence": int(row["sequence"]),
            "event_type": row["event_type"],
            "skill_id": row["skill_id"],
            "semantic_version": row["semantic_version"],
            "candidate_id": row["candidate_id"],
            "candidate_revision": (
                int(row["candidate_revision"])
                if row["candidate_revision"] is not None
                else None
            ),
            "task_id": row["task_id"],
            "session_id": row["session_id"],
            "correlation_id": row["correlation_id"],
            "actor_type": row["actor_type"],
            "actor_id": row["actor_id"],
            "reason_code": row["reason_code"],
            "reference_ids": json.loads(row["reference_ids_json"]),
            "event_hash": row["event_hash"],
            "created_at": row["created_at"],
        }
        expected = event.model_dump(mode="json")
        expected["created_at"] = _iso(event.created_at)
        if columns != expected:
            raise LearningIntegrityError("skill event index integrity failure")
        return event


__all__ = [
    "SkillRegistry",
    "SkillRegistryError",
    "SkillVersionConflictError",
]
