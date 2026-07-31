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
    Migration(
        version=2,
        statements=(
            """
            CREATE TABLE IF NOT EXISTS skill_manifests (
                content_hash TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(skill_id, semantic_version),
                FOREIGN KEY(candidate_id, candidate_revision)
                    REFERENCES candidate_revisions(candidate_id, revision)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_versions (
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                registry_revision INTEGER NOT NULL CHECK(registry_revision >= 1),
                manifest_hash TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_revision INTEGER NOT NULL,
                supersedes_version TEXT,
                record_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(skill_id, semantic_version),
                UNIQUE(skill_id, registry_revision),
                UNIQUE(manifest_hash),
                FOREIGN KEY(manifest_hash) REFERENCES skill_manifests(content_hash),
                FOREIGN KEY(candidate_id, candidate_revision)
                    REFERENCES candidate_revisions(candidate_id, revision),
                FOREIGN KEY(skill_id, supersedes_version)
                    REFERENCES skill_versions(skill_id, semantic_version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_version_heads (
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL,
                state_revision INTEGER NOT NULL CHECK(state_revision >= 1),
                manifest_hash TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_revision INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(skill_id, semantic_version),
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(manifest_hash) REFERENCES skill_manifests(content_hash),
                FOREIGN KEY(candidate_id, candidate_revision)
                    REFERENCES candidate_revisions(candidate_id, revision)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_candidate_links (
                link_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_revision INTEGER NOT NULL,
                manifest_hash TEXT NOT NULL,
                link_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(skill_id, semantic_version, candidate_id, candidate_revision),
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(candidate_id, candidate_revision)
                    REFERENCES candidate_revisions(candidate_id, revision),
                FOREIGN KEY(manifest_hash) REFERENCES skill_manifests(content_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_verification_runs (
                run_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_revision INTEGER NOT NULL,
                manifest_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                fixture_ids_json TEXT NOT NULL,
                holdout_fixture_ids_json TEXT NOT NULL,
                run_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(candidate_id, candidate_revision)
                    REFERENCES candidate_revisions(candidate_id, revision),
                FOREIGN KEY(manifest_hash) REFERENCES skill_manifests(content_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_test_results (
                result_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                test_id TEXT NOT NULL,
                test_type TEXT NOT NULL,
                fixture_id TEXT NOT NULL,
                passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
                result_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, test_id),
                FOREIGN KEY(run_id) REFERENCES skill_verification_runs(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_promotion_records (
                promotion_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_revision INTEGER NOT NULL,
                manifest_hash TEXT NOT NULL,
                decision TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                record_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(candidate_id, candidate_revision)
                    REFERENCES candidate_revisions(candidate_id, revision),
                FOREIGN KEY(manifest_hash) REFERENCES skill_manifests(content_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_activation_records (
                activation_id TEXT PRIMARY KEY,
                scope_key TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                previous_skill_id TEXT,
                previous_semantic_version TEXT,
                expected_scope_revision INTEGER NOT NULL
                    CHECK(expected_scope_revision >= 0),
                target_scope_revision INTEGER NOT NULL
                    CHECK(target_scope_revision >= 1),
                manifest_hash TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                record_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(previous_skill_id, previous_semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(manifest_hash) REFERENCES skill_manifests(content_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_scope_heads (
                scope_key TEXT PRIMARY KEY,
                active_skill_id TEXT NOT NULL,
                active_semantic_version TEXT NOT NULL,
                active_manifest_hash TEXT NOT NULL,
                scope_revision INTEGER NOT NULL CHECK(scope_revision >= 1),
                activation_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(active_skill_id, active_semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(active_manifest_hash)
                    REFERENCES skill_manifests(content_hash),
                FOREIGN KEY(activation_id)
                    REFERENCES skill_activation_records(activation_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_deprecation_records (
                deprecation_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                expected_state_revision INTEGER NOT NULL
                    CHECK(expected_state_revision >= 1),
                target_state_revision INTEGER NOT NULL
                    CHECK(target_state_revision >= 2),
                idempotency_key TEXT NOT NULL UNIQUE,
                record_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_rollback_records (
                rollback_id TEXT PRIMARY KEY,
                scope_key TEXT NOT NULL,
                from_skill_id TEXT NOT NULL,
                from_semantic_version TEXT NOT NULL,
                target_skill_id TEXT NOT NULL,
                target_semantic_version TEXT NOT NULL,
                expected_scope_revision INTEGER NOT NULL
                    CHECK(expected_scope_revision >= 1),
                target_scope_revision INTEGER NOT NULL
                    CHECK(target_scope_revision >= 2),
                activation_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                record_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(from_skill_id, from_semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(target_skill_id, target_semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(activation_id)
                    REFERENCES skill_activation_records(activation_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_execution_records (
                execution_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                outcome TEXT NOT NULL,
                effect_known INTEGER NOT NULL CHECK(effect_known IN (0, 1)),
                record_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                UNIQUE(task_id, skill_id, semantic_version),
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(manifest_hash) REFERENCES skill_manifests(content_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_execution_pins (
                pin_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                scope_revision INTEGER NOT NULL CHECK(scope_revision >= 1),
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version),
                FOREIGN KEY(manifest_hash) REFERENCES skill_manifests(content_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_metric_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                snapshot_version INTEGER NOT NULL CHECK(snapshot_version >= 1),
                snapshot_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(skill_id, semantic_version, snapshot_version),
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS candidate_conflict_resolutions (
                resolution_id TEXT PRIMARY KEY,
                conflict_id TEXT NOT NULL,
                left_candidate_id TEXT NOT NULL,
                left_revision INTEGER NOT NULL,
                right_candidate_id TEXT NOT NULL,
                right_revision INTEGER NOT NULL,
                decision TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                resolution_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK(left_candidate_id <> right_candidate_id),
                FOREIGN KEY(conflict_id)
                    REFERENCES candidate_conflict_links(conflict_id),
                FOREIGN KEY(left_candidate_id, left_revision)
                    REFERENCES candidate_revisions(candidate_id, revision),
                FOREIGN KEY(right_candidate_id, right_revision)
                    REFERENCES candidate_revisions(candidate_id, revision)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_package_records (
                package_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                direction TEXT NOT NULL,
                package_hash TEXT NOT NULL,
                quarantined INTEGER NOT NULL CHECK(quarantined IN (0, 1)),
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(skill_id, semantic_version)
                    REFERENCES skill_versions(skill_id, semantic_version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_import_quarantine_records (
                package_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                semantic_version TEXT NOT NULL,
                package_hash TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS skill_idempotency_records (
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
            CREATE TABLE IF NOT EXISTS skill_audit_events (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                skill_id TEXT,
                semantic_version TEXT,
                candidate_id TEXT,
                candidate_revision INTEGER,
                task_id TEXT,
                session_id TEXT,
                correlation_id TEXT NOT NULL,
                actor_type TEXT,
                actor_id TEXT,
                reason_code TEXT NOT NULL,
                reference_ids_json TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK((skill_id IS NULL) = (semantic_version IS NULL)),
                CHECK((actor_type IS NULL) = (actor_id IS NULL))
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_skill_versions_skill
            ON skill_versions(skill_id, registry_revision)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_skill_events_sequence
            ON skill_audit_events(sequence)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_skill_executions_version
            ON skill_execution_records(skill_id, semantic_version)
            """,
        ),
    ),
    Migration(
        version=3,
        statements=(
            """
            CREATE TABLE IF NOT EXISTS routing_recommendations (
                recommendation_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                recommended_route TEXT NOT NULL,
                skill_id TEXT,
                semantic_version TEXT,
                expected_risk INTEGER NOT NULL CHECK(expected_risk BETWEEN 0 AND 4),
                confidence REAL NOT NULL CHECK(confidence BETWEEN 0.0 AND 1.0),
                sample_size INTEGER NOT NULL CHECK(sample_size >= 0),
                recommendation_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK((skill_id IS NULL) = (semantic_version IS NULL)),
                UNIQUE(task_id, recommendation_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS routing_comparisons (
                comparison_id TEXT PRIMARY KEY,
                recommendation_id TEXT NOT NULL UNIQUE,
                actual_route TEXT NOT NULL,
                comparison_result TEXT NOT NULL,
                comparison_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(recommendation_id)
                    REFERENCES routing_recommendations(recommendation_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS feedback_revisions (
                feedback_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                answer_id TEXT,
                execution_id TEXT,
                actor TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                supersedes_revision INTEGER,
                revoked_at TEXT,
                feedback_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(feedback_id, revision),
                CHECK((answer_id IS NULL) <> (execution_id IS NULL)),
                CHECK(
                    (revision = 1 AND supersedes_revision IS NULL)
                    OR
                    (revision > 1 AND supersedes_revision = revision - 1)
                ),
                UNIQUE(feedback_id, feedback_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS feedback_heads (
                feedback_id TEXT PRIMARY KEY,
                current_revision INTEGER NOT NULL CHECK(current_revision >= 1),
                current_feedback_hash TEXT NOT NULL,
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                revoked INTEGER NOT NULL CHECK(revoked IN (0, 1)),
                updated_at TEXT NOT NULL,
                FOREIGN KEY(feedback_id, current_revision)
                    REFERENCES feedback_revisions(feedback_id, revision)
                    DEFERRABLE INITIALLY DEFERRED
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS feedback_candidate_hints (
                hint_id TEXT PRIMARY KEY,
                feedback_id TEXT NOT NULL,
                feedback_revision INTEGER NOT NULL,
                candidate_type TEXT NOT NULL,
                source_priority TEXT NOT NULL,
                hint_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(feedback_id, feedback_revision),
                FOREIGN KEY(feedback_id, feedback_revision)
                    REFERENCES feedback_revisions(feedback_id, revision)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS phase7_idempotency_records (
                namespace TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                result_references_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(namespace, idempotency_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS phase7_audit_events (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                actor TEXT,
                reference_ids_json TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_routing_task_created
            ON routing_recommendations(task_id, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_feedback_task_created
            ON feedback_revisions(task_id, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_phase7_events_task_sequence
            ON phase7_audit_events(task_id, sequence)
            """,
        ),
    ),
)


__all__ = ["MIGRATIONS", "Migration"]
