"""Local, unsigned SHA-256 skill-package export and quarantine import."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.evaluation.models import Digest, Identifier
from openjarvis.learning.lifecycle.models import ActorType
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
from openjarvis.learning.skills.registry_models import SkillAuditEventType
from openjarvis.learning.skills.verification import (
    SkillTestCase,
    SkillVerificationRecord,
)
from openjarvis.learning.store.repository import (
    LearningIntegrityError,
    LearningRecordNotFoundError,
)

_MAX_PACKAGE_BYTES = 2 * 1024 * 1024
_FORBIDDEN_PACKAGE_PATTERNS = (
    re.compile(r"\b(?:eval|exec)\s*\(", re.IGNORECASE),
    re.compile(r"\bpickle\s*\.\s*(?:load|loads)\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:powershell|cmd\.exe|bash|sh)\s+(?:-|/)", re.IGNORECASE),
    re.compile(
        r"\b(?:ignore|override)\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE
    ),
    re.compile(r"\b(?:system prompt|jailbreak|full_access)\b", re.IGNORECASE),
    re.compile(r"(?:https?|ftp)://", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PackageDirection(str, Enum):
    EXPORT = "export"
    IMPORT = "import"


class _PackagePayload(StrictFrozenModel):
    package_schema_version: Literal["1.0"] = "1.0"
    package_id: Identifier
    skill_id: SkillIdentifier
    semantic_version: SemanticVersion
    registry_revision: int = Field(ge=1)
    manifest: SkillManifest
    tests: tuple[SkillTestCase, ...]
    evidence_digests: tuple[Digest, ...]
    integrity_mode: Literal["sha256_only_unsigned"] = "sha256_only_unsigned"
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @field_validator("tests")
    @classmethod
    def _tests_required(
        cls, values: tuple[SkillTestCase, ...]
    ) -> tuple[SkillTestCase, ...]:
        by_id = {(item.test_id, item.test_version): item for item in values}
        if not by_id:
            raise ValueError("skill package requires versioned tests")
        if len(by_id) != len(values):
            raise ValueError("skill package test identities must be unique")
        return tuple(by_id[key] for key in sorted(by_id))

    @field_validator("evidence_digests")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("skill package requires evidence digests")
        return values

    @model_validator(mode="after")
    def _identity_contract(self) -> Self:
        if (
            self.skill_id != self.manifest.skill_id
            or self.semantic_version != self.manifest.semantic_version
        ):
            raise ValueError("package identity differs from manifest")
        return self


class SkillPackage(_PackagePayload):
    package_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillPackage:
        payload = _PackagePayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "package_hash": _digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"package_hash"})
        if self.package_hash != _digest(payload):
            raise ValueError("skill package_hash mismatch")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


class _PackageRecordPayload(StrictFrozenModel):
    record_id: Identifier
    package: SkillPackage
    direction: PackageDirection
    quarantined: bool
    actor_type: ActorType
    actor_id: Identifier
    correlation_id: Identifier
    idempotency_key: Identifier
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def _direction_contract(self) -> Self:
        if self.quarantined != (self.direction is PackageDirection.IMPORT):
            raise ValueError("every import and only imports remain quarantined")
        return self


class SkillPackageRecord(_PackageRecordPayload):
    record_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillPackageRecord:
        payload = _PackageRecordPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "record_hash": _digest(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"record_hash"})
        if self.record_hash != _digest(payload):
            raise ValueError("package record_hash mismatch")
        return self


class LocalSkillPackageService:
    """Export local metadata packages and import them only into quarantine."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def export_package(
        self,
        *,
        skill_id: str,
        semantic_version: str,
        destination: str | Path,
        actor_type: ActorType,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> SkillPackageRecord:
        self._validate_request(actor_id, correlation_id, idempotency_key)
        destination = self._local_path(destination, extension=".json")
        request_digest = _digest(
            {
                "operation": "skill.package.export",
                "skill_id": skill_id,
                "semantic_version": semantic_version,
                "destination": str(destination),
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "correlation_id": correlation_id,
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.package.export",
                request_digest=request_digest,
            )
            if replay is not None:
                record = self._export_record(connection, replay["record_id"])
                self._write_once(destination, record.package.canonical_bytes())
                return record
            head = self.registry._head(connection, skill_id, semantic_version)
            if head.lifecycle_state.value not in {
                "promoted",
                "active",
                "deprecated",
                "rolled_back",
            }:
                raise SkillRegistryError("only promoted skill versions may export")
            manifest = self.registry._manifest(connection, skill_id, semantic_version)
            version = self.registry._version(connection, skill_id, semantic_version)
            verification = self._latest_verification(
                connection, skill_id, semantic_version
            )
            evidence_digests = {item.source_digest for item in manifest.provenance} | {
                item.evidence_digest for item in manifest.provenance
            }
            evidence_digests.update(verification.evidence_digests)
            package = SkillPackage.create(
                {
                    "package_id": f"skill_package_{uuid.uuid4().hex}",
                    "skill_id": skill_id,
                    "semantic_version": semantic_version,
                    "registry_revision": version.registry_revision,
                    "manifest": manifest,
                    "tests": verification.run.test_cases,
                    "evidence_digests": tuple(evidence_digests),
                    "created_at": _now(),
                }
            )
            self._scan(package.canonical_bytes())
            record = SkillPackageRecord.create(
                {
                    "record_id": f"package_export_{uuid.uuid4().hex}",
                    "package": package,
                    "direction": PackageDirection.EXPORT,
                    "quarantined": False,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "correlation_id": correlation_id,
                    "idempotency_key": idempotency_key,
                    "created_at": _now(),
                }
            )
            connection.execute(
                """
                INSERT INTO skill_package_records(
                    package_id, skill_id, semantic_version, direction,
                    package_hash, quarantined, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    skill_id,
                    semantic_version,
                    record.direction.value,
                    package.package_hash,
                    0,
                    record.model_dump_json(),
                    _iso(record.created_at),
                ),
            )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.package.export",
                request_digest=request_digest,
                references={"record_id": record.record_id},
            )
        self._write_once(destination, package.canonical_bytes())
        return record

    def import_package(
        self,
        *,
        source: str | Path,
        actor_type: ActorType,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> SkillPackageRecord:
        self._validate_request(actor_id, correlation_id, idempotency_key)
        source = self._local_path(source, extension=".json")
        data = source.read_bytes()
        if len(data) > _MAX_PACKAGE_BYTES:
            raise SkillRegistryError("skill package exceeds local size limit")
        self._scan(data)
        try:
            package = SkillPackage.model_validate_json(data)
        except Exception as exc:
            raise SkillRegistryError("skill package schema or hash is invalid") from exc
        package.manifest.validate_tool_bindings(self.registry.tool_catalog)
        request_digest = _digest(
            {
                "operation": "skill.package.import",
                "source_digest": _digest(json.loads(data)),
                "package_hash": package.package_hash,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "correlation_id": correlation_id,
            }
        )
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.package.import",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._import_record(connection, replay["record_id"])
            record = SkillPackageRecord.create(
                {
                    "record_id": f"package_import_{uuid.uuid4().hex}",
                    "package": package,
                    "direction": PackageDirection.IMPORT,
                    "quarantined": True,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "correlation_id": correlation_id,
                    "idempotency_key": idempotency_key,
                    "created_at": _now(),
                }
            )
            connection.execute(
                """
                INSERT INTO skill_import_quarantine_records(
                    package_id, skill_id, semantic_version, package_hash,
                    record_hash, idempotency_key, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    package.skill_id,
                    package.semantic_version,
                    package.package_hash,
                    record.record_hash,
                    idempotency_key,
                    record.model_dump_json(),
                    _iso(record.created_at),
                ),
            )
            self.registry._append_event(
                connection,
                event_type=SkillAuditEventType.IMPORT_QUARANTINED,
                skill_id=package.skill_id,
                semantic_version=package.semantic_version,
                candidate_id=None,
                candidate_revision=None,
                correlation_id=correlation_id,
                actor_type=actor_type,
                actor_id=actor_id,
                reason_code="local_package_import_quarantined",
                reference_ids=(record.record_id, package.package_id),
                created_at=record.created_at,
            )
            self.registry._complete_idempotency(
                connection,
                key=idempotency_key,
                operation="skill.package.import",
                request_digest=request_digest,
                references={"record_id": record.record_id},
            )
            return record

    @staticmethod
    def _validate_request(
        actor_id: str, correlation_id: str, idempotency_key: str
    ) -> None:
        for value, field_name in (
            (actor_id, "actor_id"),
            (correlation_id, "correlation_id"),
            (idempotency_key, "idempotency_key"),
        ):
            _validate_identifier(value, field_name)

    @staticmethod
    def _local_path(value: str | Path, *, extension: str) -> Path:
        raw = str(value)
        if "://" in raw:
            raise SkillRegistryError("remote package sources are forbidden")
        path = Path(value).expanduser().resolve(strict=False)
        if path.suffix.lower() != extension:
            raise SkillRegistryError("skill packages must use local JSON files")
        return path

    @staticmethod
    def _scan(data: bytes) -> None:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillRegistryError("skill package must be UTF-8 JSON") from exc
        if any(pattern.search(text) for pattern in _FORBIDDEN_PACKAGE_PATTERNS):
            raise SkillRegistryError("skill package contains forbidden content")

    @staticmethod
    def _write_once(path: Path, data: bytes) -> None:
        if path.exists():
            if path.read_bytes() != data:
                raise SkillRegistryError("package destination already has other data")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _latest_verification(connection, skill_id, semantic_version):
        row = connection.execute(
            """
            SELECT payload_json FROM skill_verification_runs
            WHERE skill_id = ? AND semantic_version = ? AND status = 'passed'
            ORDER BY completed_at DESC, run_id DESC LIMIT 1
            """,
            (skill_id, semantic_version),
        ).fetchone()
        if row is None:
            raise SkillRegistryError("package export requires passed verification")
        try:
            return SkillVerificationRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError("verification integrity failure") from exc

    @staticmethod
    def _export_record(connection, record_id: str) -> SkillPackageRecord:
        row = connection.execute(
            "SELECT * FROM skill_package_records WHERE package_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("package export record not found")
        return LocalSkillPackageService._validate_record_row(row, imported=False)

    @staticmethod
    def _import_record(connection, record_id: str) -> SkillPackageRecord:
        row = connection.execute(
            "SELECT * FROM skill_import_quarantine_records WHERE package_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("package import record not found")
        return LocalSkillPackageService._validate_record_row(row, imported=True)

    @staticmethod
    def _validate_record_row(row, *, imported: bool) -> SkillPackageRecord:
        try:
            record = SkillPackageRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError("package record integrity failure") from exc
        if (
            record.record_id != row["package_id"]
            or record.package.skill_id != row["skill_id"]
            or record.package.semantic_version != row["semantic_version"]
            or record.package.package_hash != row["package_hash"]
            or _iso(record.created_at) != row["created_at"]
            or record.quarantined != imported
        ):
            raise LearningIntegrityError("package record index failure")
        if imported:
            if (
                record.record_hash != row["record_hash"]
                or record.idempotency_key != row["idempotency_key"]
            ):
                raise LearningIntegrityError("package import index failure")
        return record


__all__ = [
    "LocalSkillPackageService",
    "PackageDirection",
    "SkillPackage",
    "SkillPackageRecord",
]
