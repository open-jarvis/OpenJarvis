from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openjarvis.learning.candidates import CandidateExtractor, ExtractionResult
from openjarvis.learning.evaluation import TraceEvaluation
from openjarvis.learning.store import (
    LearningIntegrityError,
    LearningRepository,
    SQLiteLearningDatabase,
)

from .conftest import NOW, envelope, ingest, make_evaluation

EXPECTED_TABLES = {
    "learning_schema_migrations",
    "trace_evaluations",
    "extraction_runs",
    "candidate_heads",
    "candidate_revisions",
    "candidate_transition_events",
    "candidate_duplicate_links",
    "candidate_conflict_links",
    "learning_idempotency_records",
    "learning_audit_events",
}


def test_migration_creates_required_schema(database_path: Path) -> None:
    database = SQLiteLearningDatabase(database_path)
    assert database.initialize() == (1,)
    with database.reader() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    assert EXPECTED_TABLES <= {row["name"] for row in rows}


def test_migration_is_idempotent(database_path: Path) -> None:
    database = SQLiteLearningDatabase(database_path)
    assert database.initialize() == (1,)
    assert database.initialize() == ()


def test_wal_foreign_keys_and_busy_timeout(database_path: Path) -> None:
    database = SQLiteLearningDatabase(database_path, busy_timeout_ms=4321)
    database.initialize()
    with database.reader() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 4321


def test_database_requires_absolute_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        SQLiteLearningDatabase(Path("relative.sqlite3"))


def test_evaluation_round_trip_is_immutable(repository: LearningRepository) -> None:
    evaluation = make_evaluation()
    assert repository.persist_evaluation(
        evaluation,
        idempotency_key="evaluation_once",
        correlation_id="correlation_evaluation",
    )
    stored = repository.get_evaluation(evaluation.evaluation_id)
    assert stored == evaluation
    assert stored.evaluation_hash == stored.recompute_hash()


def test_same_evaluation_is_idempotent(repository: LearningRepository) -> None:
    evaluation = make_evaluation()
    first = repository.persist_evaluation(
        evaluation,
        idempotency_key="evaluation_first",
        correlation_id="correlation_first",
    )
    second = repository.persist_evaluation(
        evaluation,
        idempotency_key="evaluation_second",
        correlation_id="correlation_second",
    )
    assert first is True
    assert second is False


def test_secret_like_idempotency_key_is_rejected(
    repository: LearningRepository,
) -> None:
    evaluation = make_evaluation()
    secret_like = "sk-" + "A" * 24
    with pytest.raises(ValueError, match="secret-like"):
        repository.persist_evaluation(
            evaluation,
            idempotency_key=secret_like,
            correlation_id="correlation_secret_guard",
        )


def test_same_evaluation_id_with_other_hash_is_rejected(
    repository: LearningRepository,
) -> None:
    original = make_evaluation()
    changed = make_evaluation(task_type="synthetic.changed")
    repository.persist_evaluation(
        original,
        idempotency_key="evaluation_original",
        correlation_id="correlation_original",
    )
    with pytest.raises(LearningIntegrityError, match="different hash"):
        repository.persist_evaluation(
            changed,
            idempotency_key="evaluation_changed",
            correlation_id="correlation_changed",
        )


def test_multiple_evaluator_versions_for_same_input_are_allowed(
    repository: LearningRepository,
) -> None:
    first = make_evaluation(
        evaluation_id="evaluation_v1",
        evaluator_version="1.0.0",
        input_digest="a" * 64,
    )
    second = make_evaluation(
        evaluation_id="evaluation_v2",
        evaluator_version="2.0.0",
        input_digest="a" * 64,
    )
    for index, evaluation in enumerate((first, second)):
        repository.persist_evaluation(
            evaluation,
            idempotency_key=f"evaluation_version_{index}",
            correlation_id="correlation_versions",
        )
    assert repository.evaluations_by_input_digest("a" * 64) == (first, second)


def test_manipulated_evaluation_hash_is_rejected(
    repository: LearningRepository,
) -> None:
    evaluation = make_evaluation()
    payload = {
        field_name: getattr(evaluation, field_name)
        for field_name in type(evaluation).model_fields
    }
    payload["evaluation_hash"] = "f" * 64
    manipulated = TraceEvaluation.model_construct(**payload)
    with pytest.raises(LearningIntegrityError, match="evaluation hash"):
        repository.persist_evaluation(
            manipulated,
            idempotency_key="evaluation_manipulated",
            correlation_id="correlation_manipulated",
        )


def test_extraction_run_round_trip(
    repository: LearningRepository,
    extraction_factory,
) -> None:
    evaluation, result = extraction_factory()
    ingest(repository, evaluation, result)
    assert repository.get_extraction_run(result.run_id) == result
    assert repository.extraction_runs_by_hash(result.run_hash) == (result,)


def test_manipulated_run_hash_is_rejected(
    repository: LearningRepository,
    extraction_factory,
) -> None:
    evaluation, result = extraction_factory()
    payload = {
        field_name: getattr(result, field_name)
        for field_name in type(result).model_fields
    }
    payload["run_hash"] = "f" * 64
    manipulated = ExtractionResult.model_construct(**payload)
    with pytest.raises(LearningIntegrityError, match="run hash"):
        ingest(repository, evaluation, manipulated)


def test_same_run_id_with_different_hash_rolls_back(
    repository: LearningRepository,
) -> None:
    first_evaluation = make_evaluation()
    first = CandidateExtractor().extract((envelope(first_evaluation),), created_at=NOW)
    ingest(repository, first_evaluation, first, key="run_first")
    second_evaluation = make_evaluation(
        evaluation_id="evaluation_second",
        task_id="task_second",
        session_id="session_second",
        trace_id="trace_second",
        task_type="synthetic.changed",
    )
    second = (
        CandidateExtractor()
        .extract((envelope(second_evaluation),), created_at=NOW)
        .model_copy(update={"run_id": first.run_id})
    )
    with pytest.raises(LearningIntegrityError, match="different hash"):
        ingest(repository, second_evaluation, second, key="run_second")
    with pytest.raises(Exception):
        repository.get_evaluation(second_evaluation.evaluation_id)


def test_tampered_persisted_evaluation_is_detected(
    repository: LearningRepository,
) -> None:
    evaluation = make_evaluation()
    repository.persist_evaluation(
        evaluation,
        idempotency_key="evaluation_tamper",
        correlation_id="correlation_tamper",
    )
    with repository.database.transaction() as connection:
        connection.execute(
            """
            UPDATE trace_evaluations SET payload_json = ?
            WHERE evaluation_id = ?
            """,
            ("{}", evaluation.evaluation_id),
        )
    with pytest.raises(LearningIntegrityError, match="evaluation integrity"):
        repository.get_evaluation(evaluation.evaluation_id)


def test_tampered_persisted_extraction_is_detected(
    repository: LearningRepository,
    extraction_factory,
) -> None:
    evaluation, result = extraction_factory()
    ingest(repository, evaluation, result, key="run_tamper_persisted")
    with repository.database.transaction() as connection:
        connection.execute(
            "UPDATE extraction_runs SET payload_json = ? WHERE run_id = ?",
            ("{}", result.run_id),
        )
    with pytest.raises(LearningIntegrityError, match="extraction integrity"):
        repository.get_extraction_run(result.run_id)


def test_foreign_key_prevents_orphan_head(database_path: Path) -> None:
    database = SQLiteLearningDatabase(database_path)
    database.initialize()
    with pytest.raises(sqlite3.IntegrityError), database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO candidate_heads(
                candidate_id, duplicate_signature, current_revision,
                current_content_hash, state, project, scope,
                candidate_type, proposed_destination, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "candidate_orphan",
                "a" * 64,
                1,
                "b" * 64,
                "proposed",
                "project_a",
                "project",
                "fact",
                "learning_review",
                NOW.isoformat(),
            ),
        )
