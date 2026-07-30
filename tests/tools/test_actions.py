"""Structured tool proposal/action persistence tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openjarvis.tasks.policy import RiskLevel
from openjarvis.tools.action_store import (
    ActionIdempotencyConflict,
    ActionStore,
    ActionStoreError,
)
from openjarvis.tools.actions import (
    ActionStatus,
    ParameterSource,
    ToolAction,
    ToolArtifact,
    ToolEvent,
    ToolProposal,
    VerificationStatus,
)
from openjarvis.tools.manifest import SideEffectClass


def _proposal(**changes) -> ToolProposal:
    payload = {
        "task_id": "task-1",
        "session_id": "session-1",
        "correlation_id": "correlation-1",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "item_id": "item-1",
        "tool_id": "file.read",
        "arguments": {"path": "note.txt"},
        "expected_result": "The bounded text is returned.",
        "expected_side_effect": SideEffectClass.LOCAL_READ,
        "risk_level": RiskLevel.READ_ONLY,
        "capability": "file:read",
        "target": "note.txt",
        "verification_plan": "Hash the observed file.",
        "undo_plan": "Not applicable for a read.",
        "idempotency_key": "read-note-once",
        "timeout_seconds": 5,
        "rationale": "The user requested this note.",
        "parameter_sources": {"path": ParameterSource.USER},
    }
    payload.update(changes)
    return ToolProposal(**payload)


def test_parameter_source_required_for_every_argument() -> None:
    with pytest.raises(ValidationError, match="parameter_sources mismatch"):
        _proposal(parameter_sources={})


def test_proposal_idempotency_returns_original(tmp_path: Path) -> None:
    store = ActionStore(tmp_path / "actions.db")
    first = store.put_proposal(_proposal())
    repeated = store.put_proposal(_proposal())
    assert repeated.proposal_id == first.proposal_id
    store.close()


def test_idempotency_conflict_is_rejected(tmp_path: Path) -> None:
    store = ActionStore(tmp_path / "actions.db")
    store.put_proposal(_proposal())
    with pytest.raises(ActionIdempotencyConflict):
        store.put_proposal(_proposal(target="different.txt"))
    store.close()


def test_action_event_and_artifact_keep_full_correlation(tmp_path: Path) -> None:
    store = ActionStore(tmp_path / "actions.db")
    proposal = store.put_proposal(_proposal())
    action = store.put_action(
        ToolAction.from_proposal(
            proposal,
            manifest_version="1.0.0",
            effective_risk=RiskLevel.READ_ONLY,
        )
    )
    action = store.transition(action.action_id, ActionStatus.VALIDATED)
    action = store.transition(
        action.action_id,
        ActionStatus.RUNNING,
        tool_run_id="run-1",
    )
    event = store.append_event(
        ToolEvent(
            event_type="tool.started",
            task_id=action.task_id,
            session_id=action.session_id,
            correlation_id=action.correlation_id,
            thread_id=action.thread_id,
            turn_id=action.turn_id,
            item_id=action.item_id,
            proposal_id=action.proposal_id,
            action_id=action.action_id,
            tool_run_id="run-1",
        )
    )
    artifact = store.put_artifact(
        ToolArtifact(
            task_id=action.task_id,
            session_id=action.session_id,
            correlation_id=action.correlation_id,
            thread_id=action.thread_id,
            turn_id=action.turn_id,
            item_id=action.item_id,
            proposal_id=action.proposal_id,
            action_id=action.action_id,
            tool_run_id="run-1",
            kind="tool_output",
            path="artifacts/output.txt",
            sha256="a" * 64,
            size_bytes=4,
            media_type="text/plain",
        )
    )
    assert event.correlation_id == proposal.correlation_id
    assert artifact.action_id == action.action_id
    assert store.list_events(action.action_id) == (event,)
    assert store.list_artifacts(action.action_id) == (artifact,)
    store.close()


def test_invalid_action_transition_is_rejected(tmp_path: Path) -> None:
    store = ActionStore(tmp_path / "actions.db")
    proposal = store.put_proposal(_proposal())
    action = store.put_action(
        ToolAction.from_proposal(
            proposal,
            manifest_version="1.0.0",
            effective_risk=RiskLevel.READ_ONLY,
        )
    )
    with pytest.raises(ActionStoreError, match="invalid action transition"):
        store.transition(
            action.action_id,
            ActionStatus.COMPLETED,
            verification_status=VerificationStatus.PASSED,
        )
    store.close()
