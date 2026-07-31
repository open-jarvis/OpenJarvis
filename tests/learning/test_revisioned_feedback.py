"""Hermetic tests for task-bound, revisioned Phase-7 feedback."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from openjarvis.learning.feedback_store import (
    FeedbackType,
    RevisionedFeedbackService,
)
from openjarvis.learning.phase7_store import (
    Phase7IdempotencyConflict,
    Phase7RevisionConflict,
)
from openjarvis.learning.store.sqlite import SQLiteLearningDatabase


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def service(tmp_path: Path) -> RevisionedFeedbackService:
    database = SQLiteLearningDatabase((tmp_path / "feedback.sqlite3").resolve())
    assert database.initialize() == (1, 2, 3)
    return RevisionedFeedbackService(database)


def test_feedback_revision_revoke_and_restart_preserve_history(
    service: RevisionedFeedbackService,
) -> None:
    created = service.record(
        task_id="task-feedback",
        session_id="session-feedback",
        correlation_id="correlation-feedback",
        answer_id="answer-1",
        execution_id=None,
        actor="local-user",
        feedback_type=FeedbackType.CORRECTION,
        structured_content={
            "target_reference": "answer-1",
            "corrected_summary": "Use the verified source instead.",
        },
        source_digest=_digest("answer-1"),
        idempotency_key="feedback-create",
    )
    assert created.record.revision == 1
    assert created.record.source_priority.value == "explicit_user_correction"
    assert created.candidate_hint is not None
    assert created.candidate_hint.candidate_type == "user_correction"
    assert created.candidate_hint.review_required is True

    revised = service.revise(
        created.record.feedback_id,
        expected_revision=1,
        actor="local-user",
        feedback_type=FeedbackType.PARTIALLY_CORRECT,
        structured_content={"summary": "The conclusion is only partly supported."},
        correlation_id="correlation-feedback-revision",
        idempotency_key="feedback-revise",
    )
    assert revised.record.revision == 2
    assert revised.candidate_hint is None
    assert service.get(created.record.feedback_id, 1) == created.record

    revoked = service.revoke(
        created.record.feedback_id,
        expected_revision=2,
        actor="local-user",
        correlation_id="correlation-feedback-revoke",
        idempotency_key="feedback-revoke",
    )
    assert revoked.record.revision == 3
    assert revoked.record.revoked_at is not None
    assert tuple(
        item.revision for item in service.history(created.record.feedback_id)
    ) == (
        1,
        2,
        3,
    )
    assert service.list_for_task("task-feedback") == (revoked.record,)


def test_feedback_is_not_approval_or_verification(
    service: RevisionedFeedbackService,
) -> None:
    outcome = service.record(
        task_id="task-yes",
        session_id="session-yes",
        correlation_id="correlation-yes",
        answer_id="answer-yes",
        execution_id=None,
        actor="local-user",
        feedback_type=FeedbackType.HELPFUL,
        structured_content={"response": "yes", "input_mode": "voice"},
        source_digest=_digest("answer-yes"),
        idempotency_key="spoken-yes",
    )
    assert outcome.record.feedback_type is FeedbackType.HELPFUL
    assert outcome.candidate_hint is None
    with service.database.reader() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM skill_promotion_records"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM skill_activation_records"
            ).fetchone()[0]
            == 0
        )


def test_feedback_cas_idempotency_and_secret_guards(
    service: RevisionedFeedbackService,
) -> None:
    arguments = {
        "task_id": "task-guard",
        "session_id": "session-guard",
        "correlation_id": "correlation-guard",
        "answer_id": None,
        "execution_id": "execution-1",
        "actor": "local-user",
        "feedback_type": FeedbackType.ACTION_FAILED,
        "structured_content": {"reason_code": "postcondition_failed"},
        "source_digest": _digest("execution-1"),
        "idempotency_key": "guard-create",
    }
    created = service.record(**arguments)
    assert service.record(**arguments).idempotent is True
    with pytest.raises(Phase7IdempotencyConflict):
        service.record(
            **{
                **arguments,
                "structured_content": {"reason_code": "different"},
            }
        )
    with pytest.raises(Phase7RevisionConflict):
        service.revise(
            created.record.feedback_id,
            expected_revision=2,
            actor="local-user",
            feedback_type=FeedbackType.INCORRECT,
            structured_content={"reason_code": "wrong"},
            correlation_id="correlation-guard-revise",
            idempotency_key="stale-revision",
        )
    with pytest.raises(ValueError, match="secret-like"):
        service.record(
            **{
                **arguments,
                "idempotency_key": "secret-feedback",
                "structured_content": {"summary": "sk-" + "a" * 24},
            }
        )
