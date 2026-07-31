"""Single-process Phase-7 learning runtime shared by API and Jarvis UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openjarvis.learning.candidates.extractor import CandidateExtractor
from openjarvis.learning.candidates.models import (
    CandidateScope,
    EvaluationEnvelope,
    EvaluationLineage,
)
from openjarvis.learning.evaluation.classifier import TraceClassifier
from openjarvis.learning.evaluation.models import (
    DEFAULT_EVALUATOR_VERSION,
    EvaluationInput,
    TraceEvaluation,
)
from openjarvis.learning.evaluation.normalization import (
    input_digest,
    normalize_snapshot,
)
from openjarvis.learning.feedback_store import RevisionedFeedbackService
from openjarvis.learning.lifecycle.conflicts import ConflictReviewService
from openjarvis.learning.phase7_store import Phase7StoreCoordinator
from openjarvis.learning.routing.shadow import ShadowRoutingService
from openjarvis.learning.skills.execution import SkillExecutionRecord
from openjarvis.learning.skills.metrics import VerifiedSkillMetricService
from openjarvis.learning.skills.packages import SkillPackageRecord
from openjarvis.learning.skills.promotion import (
    SkillActivationRecord,
    SkillDeprecationRecord,
    SkillLifecycleService,
    SkillPromotionRecord,
    SkillRollbackRecord,
)
from openjarvis.learning.skills.registry import SkillRegistry
from openjarvis.learning.skills.verification import (
    SkillVerificationRecord,
    SkillVerificationService,
)
from openjarvis.learning.store.migrations import MIGRATIONS
from openjarvis.learning.store.models import IngestOutcome
from openjarvis.learning.store.repository import LearningRepository
from openjarvis.learning.store.sqlite import SQLiteLearningDatabase
from openjarvis.tools.manifest import ToolManifestCatalog


class Phase7LearningRuntime:
    """Canonical facade over one SQLite store and existing lifecycle services."""

    def __init__(
        self,
        database: SQLiteLearningDatabase,
        *,
        tool_catalog: ToolManifestCatalog,
    ) -> None:
        self.database = database
        self.learning = LearningRepository(database)
        self.registry = SkillRegistry(
            database,
            learning=self.learning,
            tool_catalog=tool_catalog,
        )
        self.verification = SkillVerificationService(self.registry)
        self.lifecycle = SkillLifecycleService(self.registry)
        self.metrics = VerifiedSkillMetricService(self.registry)
        self.conflicts = ConflictReviewService(self.learning)
        self.routing = ShadowRoutingService(database, registry=self.registry)
        self.feedback = RevisionedFeedbackService(database)
        self.coordinator = Phase7StoreCoordinator(database)
        self.classifier = TraceClassifier()
        self.extractor = CandidateExtractor()

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        tool_catalog: ToolManifestCatalog | None = None,
    ) -> "Phase7LearningRuntime":
        database = SQLiteLearningDatabase(path.resolve())
        database.initialize()
        return cls(
            database,
            tool_catalog=tool_catalog or ToolManifestCatalog(()),
        )

    def evaluate_and_extract(
        self,
        snapshot: EvaluationInput,
        *,
        project: str,
        scope: CandidateScope,
        correlation_id: str,
        idempotency_key: str,
    ) -> tuple[TraceEvaluation, IngestOutcome]:
        normalized = normalize_snapshot(snapshot)
        normalized_digest = input_digest(normalized)
        evaluation_id = f"evaluation_{normalized_digest[:32]}"
        evaluation = self.classifier.evaluate(
            normalized,
            evaluation_id=evaluation_id,
        )
        self.learning.persist_evaluation(
            evaluation,
            idempotency_key=f"{idempotency_key}.evaluation",
            correlation_id=correlation_id,
        )
        evaluation = self.learning.get_evaluation(evaluation_id)
        extraction = self.extractor.extract(
            (
                EvaluationEnvelope(
                    evaluation=evaluation,
                    scope=scope,
                    project=project,
                    lineage=EvaluationLineage(),
                ),
            )
        )
        outcome = self.learning.ingest(
            extraction,
            (evaluation,),
            idempotency_key=f"{idempotency_key}.extraction",
            correlation_id=correlation_id,
        )
        return evaluation, outcome

    def evaluations(
        self, *, task_id: str | None = None, limit: int = 200
    ) -> tuple[TraceEvaluation, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.database.reader() as connection:
            if task_id is None:
                rows = connection.execute(
                    """
                    SELECT evaluation_id FROM trace_evaluations
                    ORDER BY created_at DESC, evaluation_id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT evaluation_id FROM trace_evaluations
                    WHERE json_extract(payload_json, '$.task_id') = ?
                    ORDER BY created_at DESC, evaluation_id DESC LIMIT ?
                    """,
                    (task_id, limit),
                ).fetchall()
            identifiers = tuple(row["evaluation_id"] for row in rows)
        return tuple(self.learning.get_evaluation(value) for value in identifiers)

    def skill_ids(self) -> tuple[str, ...]:
        with self.database.reader() as connection:
            return tuple(
                row["skill_id"]
                for row in connection.execute(
                    "SELECT DISTINCT skill_id FROM skill_versions ORDER BY skill_id"
                ).fetchall()
            )

    def skill_detail(self, skill_id: str) -> dict[str, Any]:
        versions = self.registry.versions(skill_id)
        if not versions:
            raise KeyError(skill_id)
        details = []
        for version in versions:
            head = self.registry.get_head(skill_id, version.semantic_version)
            manifest = self.registry.get_manifest(skill_id, version.semantic_version)
            details.append(
                {
                    "version": version,
                    "head": head,
                    "manifest": manifest,
                    "metrics": self.metrics.history(skill_id, version.semantic_version),
                    "verification": self._verification_history(
                        skill_id, version.semantic_version
                    ),
                    "executions": self._execution_history(
                        skill_id, version.semantic_version
                    ),
                    "rollbacks": self._rollback_history(
                        skill_id, version.semantic_version
                    ),
                    "promotions": self._promotion_history(
                        skill_id, version.semantic_version
                    ),
                    "activations": self._activation_history(
                        skill_id, version.semantic_version
                    ),
                    "deprecations": self._deprecation_history(
                        skill_id, version.semantic_version
                    ),
                    "packages": self._package_history(
                        skill_id, version.semantic_version
                    ),
                    "quarantined_imports": self._quarantined_imports(
                        skill_id, version.semantic_version
                    ),
                }
            )
        return {"skill_id": skill_id, "versions": tuple(details)}

    def task_learning(self, task_id: str) -> dict[str, Any]:
        candidates = tuple(
            candidate
            for candidate in self.learning.candidates()
            if task_id in candidate.source_task_ids
        )
        return {
            "task_id": task_id,
            "evaluations": self.evaluations(task_id=task_id),
            "candidates": candidates,
            "routing": self.routing.list(task_id=task_id),
            "feedback": self.feedback.list_for_task(task_id),
            "events": self._phase7_events(task_id),
        }

    def health(self) -> dict[str, Any]:
        integrity_errors = self.coordinator.verify_integrity()
        with self.database.reader() as connection:
            migrations = [
                {
                    "version": int(row["version"]),
                    "checksum": row["checksum"],
                }
                for row in connection.execute(
                    """
                    SELECT version, checksum FROM learning_schema_migrations
                    ORDER BY version
                    """
                ).fetchall()
            ]
            open_conflicts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM candidate_conflict_links WHERE is_open = 1"
                ).fetchone()[0]
            )
            quarantined = int(
                connection.execute(
                    "SELECT COUNT(*) FROM candidate_heads WHERE state = 'quarantined'"
                ).fetchone()[0]
            )
            pending = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM skill_version_heads
                    WHERE lifecycle_state = 'promotion_pending'
                    """
                ).fetchone()[0]
            )
            active = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM skill_version_heads
                    WHERE lifecycle_state = 'active'
                    """
                ).fetchone()[0]
            )
            latest_verification = connection.execute(
                "SELECT MAX(completed_at) FROM skill_verification_runs"
            ).fetchone()[0]
            latest_metric = connection.execute(
                "SELECT MAX(created_at) FROM skill_metric_snapshots"
            ).fetchone()[0]
            feedback_count = int(
                connection.execute("SELECT COUNT(*) FROM feedback_heads").fetchone()[0]
            )
            routing_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM routing_recommendations"
                ).fetchone()[0]
            )
        expected_migrations = [
            {"version": value.version, "checksum": value.checksum}
            for value in MIGRATIONS
        ]
        if migrations != expected_migrations:
            integrity_errors = tuple(
                sorted(set(integrity_errors + ("migration_manifest_mismatch",)))
            )
        return {
            "status": "healthy" if not integrity_errors else "degraded",
            "evaluator_version": DEFAULT_EVALUATOR_VERSION,
            "extractor_version": self.extractor.extractor_version,
            "migrations": migrations,
            "store_status": "available",
            "open_conflicts": open_conflicts,
            "quarantined_candidates": quarantined,
            "promotion_pending": pending,
            "active_skill_versions": active,
            "last_verification": latest_verification,
            "last_metric_revision": latest_metric,
            "shadow_routing": {
                "enabled": True,
                "shadow_mode": True,
                "productive_route_changes": False,
                "recommendations": routing_count,
            },
            "feedback_store": {
                "status": "available",
                "records": feedback_count,
                "approval_authority": False,
            },
            "integrity_errors": integrity_errors,
            "recovery_status": (
                "restart_readback_verified"
                if not integrity_errors
                else "integrity_gate_blocked"
            ),
        }

    def _verification_history(
        self, skill_id: str, semantic_version: str
    ) -> tuple[SkillVerificationRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT run_id FROM skill_verification_runs
                WHERE skill_id = ? AND semantic_version = ?
                ORDER BY completed_at, run_id
                """,
                (skill_id, semantic_version),
            ).fetchall()
        return tuple(self.verification.get_verification(row["run_id"]) for row in rows)

    def _execution_history(
        self, skill_id: str, semantic_version: str
    ) -> tuple[SkillExecutionRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM skill_execution_records
                WHERE skill_id = ? AND semantic_version = ?
                ORDER BY created_at, execution_id
                """,
                (skill_id, semantic_version),
            ).fetchall()
        return tuple(
            SkillExecutionRecord.model_validate_json(row["payload_json"])
            for row in rows
        )

    def _rollback_history(
        self, skill_id: str, semantic_version: str
    ) -> tuple[SkillRollbackRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM skill_rollback_records
                WHERE (from_skill_id = ? AND from_semantic_version = ?)
                   OR (target_skill_id = ? AND target_semantic_version = ?)
                ORDER BY created_at, rollback_id
                """,
                (skill_id, semantic_version, skill_id, semantic_version),
            ).fetchall()
        return tuple(
            SkillRollbackRecord.model_validate_json(row["payload_json"]) for row in rows
        )

    def _promotion_history(
        self, skill_id: str, semantic_version: str
    ) -> tuple[SkillPromotionRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM skill_promotion_records
                WHERE skill_id = ? AND semantic_version = ?
                ORDER BY created_at, promotion_id
                """,
                (skill_id, semantic_version),
            ).fetchall()
        return tuple(
            SkillPromotionRecord.model_validate_json(row["payload_json"])
            for row in rows
        )

    def _activation_history(
        self, skill_id: str, semantic_version: str
    ) -> tuple[SkillActivationRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM skill_activation_records
                WHERE skill_id = ? AND semantic_version = ?
                ORDER BY created_at, activation_id
                """,
                (skill_id, semantic_version),
            ).fetchall()
        return tuple(
            SkillActivationRecord.model_validate_json(row["payload_json"])
            for row in rows
        )

    def _deprecation_history(
        self, skill_id: str, semantic_version: str
    ) -> tuple[SkillDeprecationRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM skill_deprecation_records
                WHERE skill_id = ? AND semantic_version = ?
                ORDER BY created_at, deprecation_id
                """,
                (skill_id, semantic_version),
            ).fetchall()
        return tuple(
            SkillDeprecationRecord.model_validate_json(row["payload_json"])
            for row in rows
        )

    def _package_history(
        self, skill_id: str, semantic_version: str
    ) -> tuple[SkillPackageRecord, ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM skill_package_records
                WHERE skill_id = ? AND semantic_version = ?
                ORDER BY created_at, package_id
                """,
                (skill_id, semantic_version),
            ).fetchall()
        return tuple(
            SkillPackageRecord.model_validate_json(row["payload_json"]) for row in rows
        )

    def _quarantined_imports(
        self, skill_id: str, semantic_version: str
    ) -> tuple[dict[str, Any], ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM skill_import_quarantine_records
                WHERE skill_id = ? AND semantic_version = ?
                ORDER BY created_at, package_id
                """,
                (skill_id, semantic_version),
            ).fetchall()
        return tuple(json.loads(row["payload_json"]) for row in rows)

    def _phase7_events(self, task_id: str) -> tuple[dict[str, Any], ...]:
        with self.database.reader() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM phase7_audit_events
                WHERE task_id = ? ORDER BY sequence
                """,
                (task_id,),
            ).fetchall()
        return tuple(json.loads(row["payload_json"]) for row in rows)


__all__ = ["Phase7LearningRuntime"]
