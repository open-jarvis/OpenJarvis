"""Versioned SQLite migrations for the isolated learning store."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        joined = "\n".join(statement.strip() for statement in self.statements)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


MIGRATIONS = (
    Migration(
        version=1,
        statements=(
            """
            CREATE TABLE IF NOT EXISTS learning_schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS trace_evaluations (
                evaluation_id TEXT PRIMARY KEY,
                input_digest TEXT NOT NULL,
                evaluator_version TEXT NOT NULL,
                evaluation_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_trace_input
            ON trace_evaluations(input_digest)
            """,
            """
            CREATE TABLE IF NOT EXISTS extraction_runs (
                run_id TEXT PRIMARY KEY,
                run_hash TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                input_evaluation_ids_json TEXT NOT NULL,
                candidate_ids_json TEXT NOT NULL,
                duplicate_link_ids_json TEXT NOT NULL,
                conflict_link_ids_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_extraction_hash
            ON extraction_runs(run_hash)
            """,
            """
            CREATE TABLE IF NOT EXISTS candidate_revisions (
                candidate_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                previous_revision INTEGER,
                previous_content_hash TEXT,
                state TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                transition_id TEXT,
                ingest_id TEXT,
                payload_json TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(candidate_id, revision),
                CHECK(
                    (revision = 1 AND previous_revision IS NULL
                        AND previous_content_hash IS NULL AND ingest_id IS NOT NULL
                        AND transition_id IS NULL)
                    OR
                    (revision > 1 AND previous_revision = revision - 1
                        AND previous_content_hash IS NOT NULL
                        AND ((transition_id IS NULL) <> (ingest_id IS NULL)))
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS candidate_heads (
                candidate_id TEXT PRIMARY KEY,
                duplicate_signature TEXT NOT NULL UNIQUE,
                current_revision INTEGER NOT NULL CHECK(current_revision >= 1),
                current_content_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                project TEXT NOT NULL,
                scope TEXT NOT NULL,
                candidate_type TEXT NOT NULL,
                proposed_destination TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id, current_revision)
                    REFERENCES candidate_revisions(candidate_id, revision)
                    DEFERRABLE INITIALLY DEFERRED
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_heads_state ON candidate_heads(state)",
            """
            CREATE INDEX IF NOT EXISTS ix_heads_query
            ON candidate_heads(project, scope, candidate_type)
            """,
            """
            CREATE TABLE IF NOT EXISTS candidate_transition_events (
                transition_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                source_revision INTEGER NOT NULL,
                target_revision INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                transition_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id, source_revision)
                    REFERENCES candidate_revisions(candidate_id, revision),
                FOREIGN KEY(candidate_id, target_revision)
                    REFERENCES candidate_revisions(candidate_id, revision)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS candidate_duplicate_links (
                link_id TEXT PRIMARY KEY,
                link_hash TEXT NOT NULL,
                duplicate_signature TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                extraction_run_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES candidate_heads(candidate_id),
                FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS candidate_conflict_links (
                conflict_id TEXT PRIMARY KEY,
                conflict_hash TEXT NOT NULL,
                conflict_signature TEXT NOT NULL,
                candidate_a_id TEXT NOT NULL,
                candidate_b_id TEXT NOT NULL,
                is_open INTEGER NOT NULL CHECK(is_open IN (0, 1)),
                extraction_run_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK(candidate_a_id <> candidate_b_id),
                FOREIGN KEY(candidate_a_id) REFERENCES candidate_heads(candidate_id),
                FOREIGN KEY(candidate_b_id) REFERENCES candidate_heads(candidate_id),
                FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS learning_idempotency_records (
                idempotency_key TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                result_references_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS learning_audit_events (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                candidate_id TEXT,
                revision INTEGER,
                correlation_id TEXT NOT NULL,
                actor_type TEXT,
                actor_id TEXT,
                reason_code TEXT NOT NULL,
                reference_ids_json TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                CHECK((actor_type IS NULL) = (actor_id IS NULL))
            )
            """,
        ),
    ),
)


__all__ = ["MIGRATIONS", "Migration"]
