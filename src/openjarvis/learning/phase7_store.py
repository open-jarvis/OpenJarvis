"""Shared append-only helpers for the final Phase-7 learning surfaces."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from openjarvis.learning.store.sqlite import SQLiteLearningDatabase


class Phase7StoreError(RuntimeError):
    """Base error for the final Phase-7 append-only stores."""


class Phase7IntegrityError(Phase7StoreError):
    """Persisted hash-bound data failed verification."""


class Phase7IdempotencyConflict(Phase7StoreError):
    """An idempotency key was reused for different request semantics."""


class Phase7RevisionConflict(Phase7StoreError):
    """A compare-and-swap revision no longer matches the stored head."""


class Phase7RecordNotFound(Phase7StoreError):
    """A requested append-only record does not exist."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
)
_PRIVATE_KEYS = {
    "chain_of_thought",
    "private_payload",
    "prompt",
    "raw_task_text",
    "tool_output",
}


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc).isoformat()


def validate_identifier(value: str, field_name: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded identifier")
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise ValueError(f"{field_name} contains secret-like material")
    return value


def validate_digest(value: str, field_name: str) -> str:
    if not _DIGEST.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def safe_metadata(value: Any, *, depth: int = 0) -> Any:
    """Validate bounded metadata without retaining prompts or tool outputs."""

    if depth > 5:
        raise ValueError("structured metadata nesting is too deep")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        normalized = " ".join(value.strip().split())
        if len(normalized) > 1024:
            raise ValueError("structured metadata text exceeds 1024 characters")
        if any(pattern.search(normalized) for pattern in _SECRET_PATTERNS):
            raise ValueError("structured metadata contains secret-like material")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("structured metadata contains control characters")
        return normalized
    if isinstance(value, Mapping):
        if len(value) > 32:
            raise ValueError("structured metadata has too many fields")
        result: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not _IDENTIFIER.fullmatch(key):
                raise ValueError("structured metadata keys must be identifiers")
            if key.lower() in _PRIVATE_KEYS:
                raise ValueError(f"structured metadata field {key!r} is private")
            result[key] = safe_metadata(child, depth=depth + 1)
        return {key: result[key] for key in sorted(result)}
    if isinstance(value, (list, tuple)):
        if len(value) > 64:
            raise ValueError("structured metadata has too many values")
        return [safe_metadata(child, depth=depth + 1) for child in value]
    raise ValueError("structured metadata contains an unsupported value")


class Phase7StoreCoordinator:
    """Idempotency, audit, and integrity support shared by routing/feedback."""

    def __init__(self, database: SQLiteLearningDatabase) -> None:
        self.database = database

    def replay(
        self,
        connection: sqlite3.Connection,
        *,
        namespace: str,
        idempotency_key: str,
        operation: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        validate_identifier(namespace, "namespace")
        validate_identifier(idempotency_key, "idempotency_key")
        validate_identifier(operation, "operation")
        validate_digest(request_digest, "request_digest")
        row = connection.execute(
            """
            SELECT operation, request_digest, result_references_json
            FROM phase7_idempotency_records
            WHERE namespace = ? AND idempotency_key = ?
            """,
            (namespace, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation or row["request_digest"] != request_digest:
            raise Phase7IdempotencyConflict(
                "idempotency key was already used for a different request"
            )
        return json.loads(row["result_references_json"])

    def complete(
        self,
        connection: sqlite3.Connection,
        *,
        namespace: str,
        idempotency_key: str,
        operation: str,
        request_digest: str,
        result_references: Mapping[str, Any],
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO phase7_idempotency_records(
                namespace, idempotency_key, operation, request_digest,
                result_references_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                namespace,
                idempotency_key,
                operation,
                request_digest,
                canonical_json(result_references),
                iso(created_at),
            ),
        )

    def append_audit(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        task_id: str,
        session_id: str,
        correlation_id: str,
        actor: str | None,
        reference_ids: tuple[str, ...],
        created_at: datetime,
    ) -> str:
        for value, field_name in (
            (event_type, "event_type"),
            (task_id, "task_id"),
            (session_id, "session_id"),
            (correlation_id, "correlation_id"),
        ):
            validate_identifier(value, field_name)
        if actor is not None:
            validate_identifier(actor, "actor")
        references = tuple(sorted(set(reference_ids)))
        for reference in references:
            validate_identifier(reference, "reference_id")
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM phase7_audit_events"
            ).fetchone()[0]
        )
        event_id = f"phase7_event_{uuid.uuid4().hex}"
        payload = {
            "sequence": sequence,
            "event_id": event_id,
            "event_type": event_type,
            "task_id": task_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "actor": actor,
            "reference_ids": list(references),
            "created_at": iso(created_at),
        }
        event_hash = digest(payload)
        stored = {**payload, "event_hash": event_hash}
        connection.execute(
            """
            INSERT INTO phase7_audit_events(
                sequence, event_id, event_type, task_id, session_id,
                correlation_id, actor, reference_ids_json, event_hash,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sequence,
                event_id,
                event_type,
                task_id,
                session_id,
                correlation_id,
                actor,
                canonical_json(references),
                event_hash,
                canonical_json(stored),
                iso(created_at),
            ),
        )
        return event_id

    def verify_integrity(self) -> tuple[str, ...]:
        errors: list[str] = []
        with self.database.reader() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                errors.append("sqlite_integrity_check_failed")
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                errors.append("sqlite_foreign_key_check_failed")
            rows = connection.execute(
                """
                SELECT payload_json, event_hash
                FROM phase7_audit_events ORDER BY sequence
                """
            ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                    stored_hash = payload.pop("event_hash")
                    if (
                        stored_hash != row["event_hash"]
                        or digest(payload) != stored_hash
                    ):
                        errors.append("phase7_audit_hash_mismatch")
                        break
                except Exception:
                    errors.append("phase7_audit_decode_failed")
                    break
        return tuple(sorted(set(errors)))


__all__ = [
    "Phase7IdempotencyConflict",
    "Phase7IntegrityError",
    "Phase7RecordNotFound",
    "Phase7RevisionConflict",
    "Phase7StoreCoordinator",
    "Phase7StoreError",
    "canonical_json",
    "digest",
    "iso",
    "safe_metadata",
    "utc_now",
    "validate_digest",
    "validate_identifier",
]
