from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openjarvis.learning.candidates import CandidateExtractor, CandidateState
from openjarvis.learning.store import (
    IdempotencyConflictError,
    IngestDisposition,
    LearningIntegrityError,
    LearningRecordNotFoundError,
    LearningRepository,
    SQLiteLearningDatabase,
)

from .conftest import NOW, clone_run, envelope, ingest, make_evaluation


def test_first_candidate_gets_stable_identity(repository: LearningRepository) -> None:
    evaluation = make_evaluation()
    result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    outcome = ingest(repository, evaluation, result)
    stored = repository.get_candidate_head(outcome.candidates[0].candidate_id)
    assert stored.candidate_id == f"candidate_{stored.duplicate_signature[:32]}"
    assert stored.revision == 1
    assert outcome.candidates[0].disposition is IngestDisposition.CREATED


def test_cross_run_duplicate_uses_same_candidate_id(
    repository: LearningRepository,
) -> None:
    first_evaluation = make_evaluation()
    second_evaluation = make_evaluation(
        evaluation_id="evaluation_b",
        task_id="task_b",
        session_id="session_b",
        trace_id="trace_b",
    )
    first = CandidateExtractor().extract((envelope(first_evaluation),), created_at=NOW)
    second = CandidateExtractor().extract(
        (envelope(second_evaluation),), created_at=NOW
    )
    first_outcome = ingest(repository, first_evaluation, first, key="ingest_first")
    second_outcome = ingest(repository, second_evaluation, second, key="ingest_second")
    assert (
        first_outcome.candidates[0].candidate_id
        == second_outcome.candidates[0].candidate_id
    )
    assert second_outcome.candidates[0].revision == 2


def test_cross_run_duplicate_unions_evidence_provenance_and_independence(
    repository: LearningRepository,
) -> None:
    evaluations = tuple(
        make_evaluation(
            evaluation_id=f"evaluation_{index}",
            task_id=f"task_{index}",
            session_id=f"session_{index}",
            trace_id=f"trace_{index}",
        )
        for index in range(2)
    )
    candidate_id = ""
    for index, evaluation in enumerate(evaluations):
        result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
        outcome = ingest(
            repository,
            evaluation,
            result,
            key=f"ingest_union_{index}",
        )
        candidate_id = outcome.candidates[0].candidate_id
    candidate = repository.get_candidate_head(candidate_id)
    assert candidate.source_evaluation_ids == ("evaluation_0", "evaluation_1")
    assert len(candidate.provenance) == 2
    assert candidate.independence_count == 2
    assert len(candidate.source_evidence_ids) == 6


def test_exact_cross_run_duplicate_is_noop(repository: LearningRepository) -> None:
    evaluation = make_evaluation()
    first = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    second = clone_run(first, "extraction_clone")
    first_outcome = ingest(repository, evaluation, first, key="ingest_exact_first")
    second_outcome = ingest(repository, evaluation, second, key="ingest_exact_second")
    assert (
        second_outcome.candidates[0].candidate_id
        == first_outcome.candidates[0].candidate_id
    )
    assert second_outcome.candidates[0].revision == 1
    assert second_outcome.candidates[0].disposition is IngestDisposition.NOOP


def test_evidence_extension_creates_append_only_revision(
    repository: LearningRepository,
) -> None:
    first_evaluation = make_evaluation()
    second_evaluation = make_evaluation(
        evaluation_id="evaluation_extension",
        task_id="task_extension",
        session_id="session_extension",
        trace_id="trace_extension",
    )
    first = CandidateExtractor().extract((envelope(first_evaluation),), created_at=NOW)
    second = CandidateExtractor().extract(
        (envelope(second_evaluation),), created_at=NOW
    )
    candidate_id = (
        ingest(repository, first_evaluation, first, key="ingest_extension_first")
        .candidates[0]
        .candidate_id
    )
    ingest(repository, second_evaluation, second, key="ingest_extension_second")
    history = repository.candidate_history(candidate_id)
    assert [record.revision for record in history] == [1, 2]
    assert history[1].previous_revision == 1
    assert history[1].previous_content_hash == history[0].content_hash
    assert history[0].candidate_payload.source_evaluation_ids == ("evaluation_a",)


def test_head_points_to_latest_revision(repository: LearningRepository) -> None:
    first = make_evaluation()
    second = make_evaluation(
        evaluation_id="evaluation_latest",
        task_id="task_latest",
        session_id="session_latest",
        trace_id="trace_latest",
    )
    candidate_id = ""
    for index, evaluation in enumerate((first, second)):
        result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
        candidate_id = (
            ingest(repository, evaluation, result, key=f"ingest_latest_{index}")
            .candidates[0]
            .candidate_id
        )
    head = repository.get_candidate_head(candidate_id)
    revision = repository.get_candidate_revision(candidate_id, 2)
    assert head.revision == 2
    assert head.content_hash == revision.content_hash


def test_revision_one_automatic_state_is_safe(repository: LearningRepository) -> None:
    evaluation = make_evaluation()
    result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    candidate_id = ingest(repository, evaluation, result).candidates[0].candidate_id
    assert repository.get_candidate_revision(candidate_id, 1).state in {
        CandidateState.PROPOSED,
        CandidateState.QUARANTINED,
    }


def test_duplicate_link_is_persisted_cross_run(repository: LearningRepository) -> None:
    evaluation = make_evaluation()
    first = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    second = clone_run(first, "extraction_duplicate_link")
    ingest(repository, evaluation, first, key="duplicate_link_first")
    ingest(repository, evaluation, second, key="duplicate_link_second")
    links = repository.duplicate_links()
    assert len(links) == 1
    assert (
        links[0].candidate_id
        == repository.get_candidate_by_duplicate_signature(
            links[0].duplicate_signature
        ).candidate_id
    )


def test_tampered_duplicate_signature_is_detected(
    repository: LearningRepository,
) -> None:
    evaluation = make_evaluation()
    first = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    second = clone_run(first, "extraction_duplicate_tamper")
    ingest(repository, evaluation, first, key="duplicate_tamper_first")
    ingest(repository, evaluation, second, key="duplicate_tamper_second")
    with repository.database.transaction() as connection:
        connection.execute(
            "UPDATE candidate_duplicate_links SET duplicate_signature = ?",
            ("f" * 64,),
        )
    with pytest.raises(LearningIntegrityError, match="index is inconsistent"):
        repository.duplicate_links()


def test_same_idempotency_key_returns_same_outcome(
    repository: LearningRepository,
) -> None:
    evaluation = make_evaluation()
    result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    first = ingest(repository, evaluation, result, key="ingest_replay")
    second = ingest(repository, evaluation, result, key="ingest_replay")
    assert second.idempotent is True
    assert first.candidates == second.candidates
    assert len(repository.candidate_history(first.candidates[0].candidate_id)) == 1


def test_idempotency_key_with_other_payload_is_rejected(
    repository: LearningRepository,
) -> None:
    first_evaluation = make_evaluation()
    first = CandidateExtractor().extract((envelope(first_evaluation),), created_at=NOW)
    ingest(repository, first_evaluation, first, key="ingest_conflict")
    second_evaluation = make_evaluation(
        evaluation_id="evaluation_other",
        task_id="task_other",
        session_id="session_other",
        trace_id="trace_other",
    )
    second = CandidateExtractor().extract(
        (envelope(second_evaluation),), created_at=NOW
    )
    with pytest.raises(IdempotencyConflictError):
        ingest(repository, second_evaluation, second, key="ingest_conflict")


def test_restart_recovers_head_history_and_idempotency(
    database_path: Path,
) -> None:
    first_repository = LearningRepository(SQLiteLearningDatabase(database_path))
    first_repository.initialize()
    evaluation = make_evaluation()
    result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    first = ingest(first_repository, evaluation, result, key="restart_ingest")
    candidate_id = first.candidates[0].candidate_id

    restarted = LearningRepository(SQLiteLearningDatabase(database_path))
    restarted.initialize()
    assert restarted.get_candidate_head(candidate_id).revision == 1
    assert len(restarted.candidate_history(candidate_id)) == 1
    replay = ingest(restarted, evaluation, result, key="restart_ingest")
    assert replay.idempotent is True
    assert len(restarted.candidate_history(candidate_id)) == 1


def test_candidate_queries_filter_by_state_project_scope_and_type(
    repository: LearningRepository,
) -> None:
    evaluation = make_evaluation()
    result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    candidate_id = ingest(repository, evaluation, result).candidates[0].candidate_id
    by_state = repository.candidates(state=CandidateState.PROPOSED)
    by_metadata = repository.candidates(
        project="project_a",
        scope="project",
        candidate_type="successful_solution",
    )
    assert [item.candidate_id for item in by_state] == [candidate_id]
    assert [item.candidate_id for item in by_metadata] == [candidate_id]


def test_tampered_candidate_payload_hash_is_detected(
    repository: LearningRepository,
) -> None:
    evaluation = make_evaluation()
    result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
    candidate_id = ingest(repository, evaluation, result).candidates[0].candidate_id
    with repository.database.transaction() as connection:
        row = connection.execute(
            """
            SELECT payload_json FROM candidate_revisions
            WHERE candidate_id = ? AND revision = 1
            """,
            (candidate_id,),
        ).fetchone()
        payload = row["payload_json"].replace(
            '"title":"Verified solution', '"title":"Changed solution'
        )
        connection.execute(
            """
            UPDATE candidate_revisions SET payload_json = ?
            WHERE candidate_id = ? AND revision = 1
            """,
            (payload, candidate_id),
        )
    with pytest.raises(LearningIntegrityError, match="revision integrity"):
        repository.get_candidate_head(candidate_id)


def test_missing_parent_revision_is_detected(
    repository: LearningRepository,
) -> None:
    first = make_evaluation()
    second = make_evaluation(
        evaluation_id="evaluation_parent",
        task_id="task_parent",
        session_id="session_parent",
        trace_id="trace_parent",
    )
    candidate_id = ""
    for index, evaluation in enumerate((first, second)):
        result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)
        candidate_id = (
            ingest(repository, evaluation, result, key=f"parent_ingest_{index}")
            .candidates[0]
            .candidate_id
        )
    connection = sqlite3.connect(repository.database.path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "DELETE FROM candidate_revisions WHERE candidate_id = ? AND revision = 1",
            (candidate_id,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(LearningIntegrityError, match="parent is missing"):
        repository.get_candidate_revision(candidate_id, 2)


def test_partial_failure_rolls_back_everything(
    repository: LearningRepository,
    monkeypatch,
) -> None:
    evaluation = make_evaluation()
    result = CandidateExtractor().extract((envelope(evaluation),), created_at=NOW)

    def fail_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic crash before commit")

    monkeypatch.setattr(repository, "_append_event", fail_event)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        ingest(repository, evaluation, result, key="crash_ingest")
    with pytest.raises(LearningRecordNotFoundError):
        repository.get_extraction_run(result.run_id)
    with repository.database.reader() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM candidate_heads").fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM candidate_revisions").fetchone()[0]
            == 0
        )
