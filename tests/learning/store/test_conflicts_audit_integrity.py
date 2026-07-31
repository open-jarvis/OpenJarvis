from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from openjarvis.learning.candidates import (
    CandidateExtractor,
    CandidateState,
    ConflictPriority,
    CorrectionFeedbackContent,
    ExplicitFeedbackRecord,
    FactContent,
    FactFeedbackContent,
    FactValidity,
    FeedbackType,
    UserCorrectionContent,
)
from openjarvis.learning.lifecycle import (
    ActorType,
    QuarantineResolution,
    TransitionDeniedError,
    TransitionRequest,
)
from openjarvis.learning.store import (
    LearningIntegrityError,
    LearningRecordNotFoundError,
    LearningRepository,
)
from tests.learning.candidates.conftest import digest

from .conftest import NOW, clone_run

STORE_SOURCE = Path(__file__).resolve().parents[3] / "src" / "openjarvis" / "learning"


def _fact_feedback(feedback_id: str, value: str) -> ExplicitFeedbackRecord:
    return ExplicitFeedbackRecord(
        feedback_id=feedback_id,
        feedback_type=FeedbackType.FACT_CONFIRMATION,
        user_source_id=f"user_{feedback_id}",
        feedback_group_id=f"group_{feedback_id}",
        project="project_a",
        content=FactFeedbackContent(
            fact=FactContent(
                subject="synthetic user",
                predicate="locale",
                value=value,
                scope="user",
                validity=FactValidity.UNTIL_REVOKED,
                explicit_user_confirmation_required=False,
            )
        ),
        source_digest=digest(feedback_id),
        created_at=NOW,
    )


def _ingest_feedback(
    repository: LearningRepository,
    record: ExplicitFeedbackRecord,
    *,
    key: str,
):
    result = CandidateExtractor().extract(
        (), feedback_records=(record,), created_at=NOW
    )
    outcome = repository.ingest(
        result,
        (),
        idempotency_key=key,
        correlation_id=f"correlation_{key}",
    )
    return result, outcome


def test_cross_run_conflict_preserves_and_quarantines_both_atomically(
    repository: LearningRepository,
) -> None:
    first_result, first_outcome = _ingest_feedback(
        repository,
        _fact_feedback("feedback_alpha", "locale alpha"),
        key="conflict_alpha",
    )
    second_result, second_outcome = _ingest_feedback(
        repository,
        _fact_feedback("feedback_beta", "locale beta"),
        key="conflict_beta",
    )
    first_id = first_outcome.candidates[0].candidate_id
    second_id = second_outcome.candidates[0].candidate_id
    assert first_result.run_id != second_result.run_id
    assert first_id != second_id
    assert repository.get_candidate_head(first_id).state is CandidateState.QUARANTINED
    assert repository.get_candidate_head(second_id).state is CandidateState.QUARANTINED
    links = repository.open_conflicts()
    assert len(links) == 1
    assert set(links[0].candidate_ids) == {first_id, second_id}
    assert len(repository.candidate_history(first_id)) == 2
    assert len(repository.candidate_history(second_id)) == 2


def test_repeated_conflict_link_is_idempotent(repository: LearningRepository) -> None:
    _ingest_feedback(
        repository,
        _fact_feedback("feedback_repeat_a", "locale alpha"),
        key="repeat_a",
    )
    second_result, second_outcome = _ingest_feedback(
        repository,
        _fact_feedback("feedback_repeat_b", "locale beta"),
        key="repeat_b",
    )
    repeated = clone_run(second_result, "extraction_conflict_repeat")
    replay = repository.ingest(
        repeated,
        (),
        idempotency_key="repeat_conflict",
        correlation_id="correlation_repeat_conflict",
    )
    assert (
        replay.candidates[0].candidate_id == second_outcome.candidates[0].candidate_id
    )
    assert len(repository.open_conflicts()) == 1


def test_user_correction_priority_does_not_resolve_conflict(
    repository: LearningRepository,
) -> None:
    fact_result, fact_outcome = _ingest_feedback(
        repository,
        _fact_feedback("feedback_target", "locale alpha"),
        key="correction_target",
    )
    target = fact_result.candidates[0]
    correction = ExplicitFeedbackRecord(
        feedback_id="feedback_correction",
        feedback_type=FeedbackType.USER_CORRECTION,
        user_source_id="user_correction",
        feedback_group_id="group_correction",
        project="project_a",
        content=CorrectionFeedbackContent(
            correction=UserCorrectionContent(
                target_reference=target.duplicate_signature,
                previous_value_digest=digest("previous locale"),
                corrected_value="The locale fact is not valid",
                correction_scope="user",
            )
        ),
        source_digest=digest("feedback correction"),
        created_at=NOW,
    )
    _result, correction_outcome = _ingest_feedback(
        repository, correction, key="correction_ingest"
    )
    link = repository.open_conflicts()[0]
    assert link.priority is ConflictPriority.USER_CORRECTION
    assert link.preferred_candidate_id == correction_outcome.candidates[0].candidate_id
    assert (
        repository.get_candidate_head(fact_outcome.candidates[0].candidate_id).state
        is CandidateState.QUARANTINED
    )
    assert (
        repository.get_candidate_head(
            correction_outcome.candidates[0].candidate_id
        ).state
        is CandidateState.QUARANTINED
    )


def test_open_conflict_prevents_quarantine_resolution(
    repository: LearningRepository,
) -> None:
    _first, first_outcome = _ingest_feedback(
        repository,
        _fact_feedback("feedback_open_a", "locale alpha"),
        key="open_a",
    )
    _ingest_feedback(
        repository,
        _fact_feedback("feedback_open_b", "locale beta"),
        key="open_b",
    )
    candidate_id = first_outcome.candidates[0].candidate_id
    current = repository.get_candidate_head(candidate_id)
    resolutions = tuple(
        QuarantineResolution(
            resolution_id=f"resolution_{reason.value}",
            quarantine_reason=reason,
            evidence_digest=digest(reason.value),
            summary=f"Synthetic resolution for {reason.value}",
        )
        for reason in current.quarantine_reasons
    )
    request = TransitionRequest(
        candidate_id=candidate_id,
        expected_revision=current.revision,
        target_state=CandidateState.UNDER_REVIEW,
        actor_type=ActorType.USER,
        actor_id="user_reviewer",
        reason="Review the synthetic conflict",
        reason_code="conflict_review",
        correlation_id="correlation_conflict_review",
        idempotency_key="conflict_review",
        quarantine_resolution_records=resolutions,
    )
    with pytest.raises(TransitionDeniedError, match="open conflict"):
        repository.transition(request)


def test_conflict_transaction_rolls_back_both_quarantine_revisions(
    repository: LearningRepository,
    monkeypatch,
) -> None:
    _first, first_outcome = _ingest_feedback(
        repository,
        _fact_feedback("feedback_rollback_a", "locale alpha"),
        key="rollback_a",
    )
    second = _fact_feedback("feedback_rollback_b", "locale beta")
    second_result = CandidateExtractor().extract(
        (), feedback_records=(second,), created_at=NOW
    )

    def fail_conflict(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic conflict persistence failure")

    monkeypatch.setattr(repository, "_persist_conflict", fail_conflict)
    with pytest.raises(RuntimeError, match="conflict persistence"):
        repository.ingest(
            second_result,
            (),
            idempotency_key="rollback_b",
            correlation_id="correlation_rollback_b",
        )
    first_id = first_outcome.candidates[0].candidate_id
    assert repository.get_candidate_head(first_id).state is CandidateState.PROPOSED
    assert len(repository.candidate_history(first_id)) == 1
    with pytest.raises(LearningRecordNotFoundError):
        repository.get_candidate_by_duplicate_signature(
            second_result.candidates[0].duplicate_signature
        )


def test_event_sequence_is_stable_and_metadata_only(
    repository: LearningRepository,
) -> None:
    _ingest_feedback(
        repository,
        _fact_feedback("feedback_events", "locale alpha"),
        key="events",
    )
    events = repository.events_after()
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    serialized = " ".join(event.model_dump_json() for event in events)
    for private_field in (
        "candidate_payload",
        "trace_payload",
        "tool_output",
        "browser_dom",
        "chain_of_thought",
        "reasoning_tokens",
    ):
        assert private_field not in serialized


def test_events_after_sequence_is_incremental(repository: LearningRepository) -> None:
    _ingest_feedback(
        repository,
        _fact_feedback("feedback_event_cursor", "locale alpha"),
        key="event_cursor",
    )
    events = repository.events_after()
    assert repository.events_after(events[-2].sequence) == (events[-1],)


def test_tampered_event_hash_is_detected(repository: LearningRepository) -> None:
    _ingest_feedback(
        repository,
        _fact_feedback("feedback_event_tamper", "locale alpha"),
        key="event_tamper",
    )
    with repository.database.transaction() as connection:
        sequence = connection.execute(
            "SELECT MIN(sequence) FROM learning_audit_events"
        ).fetchone()[0]
        connection.execute(
            "UPDATE learning_audit_events SET payload_json = ? WHERE sequence = ?",
            ("{}", sequence),
        )
    with pytest.raises(LearningIntegrityError, match="audit event integrity"):
        repository.events_after()


def test_tampered_conflict_hash_is_detected(repository: LearningRepository) -> None:
    _ingest_feedback(
        repository,
        _fact_feedback("feedback_conflict_tamper_a", "locale alpha"),
        key="conflict_tamper_a",
    )
    _ingest_feedback(
        repository,
        _fact_feedback("feedback_conflict_tamper_b", "locale beta"),
        key="conflict_tamper_b",
    )
    with repository.database.transaction() as connection:
        conflict_id = connection.execute(
            "SELECT conflict_id FROM candidate_conflict_links"
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE candidate_conflict_links SET payload_json = ?
            WHERE conflict_id = ?
            """,
            ("{}", conflict_id),
        )
    with pytest.raises(LearningIntegrityError, match="conflict link integrity"):
        repository.open_conflicts()


def test_store_and_lifecycle_do_not_open_network_socket(
    repository: LearningRepository,
    monkeypatch,
) -> None:
    def fail_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("learning store attempted network access")

    monkeypatch.setattr(socket, "socket", fail_socket)
    _ingest_feedback(
        repository,
        _fact_feedback("feedback_offline", "locale alpha"),
        key="offline",
    )


@pytest.mark.parametrize(
    "blocked_root",
    ["openai", "requests", "httpx", "socket", "subprocess"],
)
def test_store_lifecycle_has_no_blocked_import(blocked_root: str) -> None:
    imported: set[str] = set()
    files = tuple((STORE_SOURCE / "store").glob("*.py")) + tuple(
        (STORE_SOURCE / "lifecycle").glob("*.py")
    )
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert blocked_root not in imported


@pytest.mark.parametrize(
    "blocked_symbol",
    [
        "Codex",
        "Ollama",
        "SkillExecutor",
        "ToolExecutor",
        "LearnedRouter",
        "SpecSearch",
        "full_access",
    ],
)
def test_store_lifecycle_has_no_blocked_runtime_symbol(blocked_symbol: str) -> None:
    files = tuple((STORE_SOURCE / "store").glob("*.py")) + tuple(
        (STORE_SOURCE / "lifecycle").glob("*.py")
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert blocked_symbol not in source


@pytest.mark.parametrize(
    "restricted_marker",
    ["jarvis-desktop", "Obsidian", "46 notes", "Phase 8"],
)
def test_store_lifecycle_has_no_restricted_data_marker(
    restricted_marker: str,
) -> None:
    files = tuple((STORE_SOURCE / "store").glob("*.py")) + tuple(
        (STORE_SOURCE / "lifecycle").glob("*.py")
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert restricted_marker not in source
