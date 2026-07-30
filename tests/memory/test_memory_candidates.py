"""Approval-gated memory candidate tests in an isolated synthetic vault."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from openjarvis.memory.candidates import (
    MemoryCandidateWorkflow,
    recognize_memory_request,
)
from openjarvis.memory.safe_write import AtomicMarkdownWriter, ConcurrentMemoryWrite
from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import CandidateStatus, ConflictState
from openjarvis.memory.vault_retrieval import VaultRetriever
from openjarvis.memory.vault_service import VaultMemoryService
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import ApprovalKind, ApprovalStatus, ExecutionLane
from openjarvis.traces.store import TraceStore


def _existing_note(
    path: Path,
    *,
    body: str,
    source: str = "manual",
    conflict_key: str | None = None,
) -> str:
    note_id = str(uuid.uuid4())
    conflict_yaml = f"conflict_key: {conflict_key}\n" if conflict_key else ""
    path.write_text(
        "---\n"
        f"id: {note_id}\n"
        "schema_version: 1\n"
        "type: fact\n"
        "status: active\n"
        "scope: personal\n"
        f"source: {source}\n"
        f"{conflict_yaml}"
        "---\n"
        f"{body.rstrip()}\n",
        encoding="utf-8",
    )
    return note_id


@pytest.fixture()
def candidate_runtime(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    task_store = TaskStore(tmp_path / "tasks.sqlite3")
    trace_store = TraceStore(tmp_path / "traces.sqlite3")
    task_store.create_task(
        task_id="task-memory",
        session_id="session-memory",
        correlation_id="correlation-memory",
        description="Remember a synthetic preference",
        execution_lane=ExecutionLane.MODEL,
        backend="codex",
        risk_level=1,
        component="test",
        cause="user_request",
        idempotency_key="create-memory-task",
    )
    index = VaultIndex(
        vault,
        tmp_path / "state" / "memory.sqlite3",
        mode="writable-test",
    )
    retriever = VaultRetriever(index)
    bridge = MemoryTaskBridge(task_store, trace_store=trace_store)
    writer = AtomicMarkdownWriter(vault, tmp_path / "restore")
    workflow = MemoryCandidateWorkflow(
        index,
        retriever,
        bridge,
        writer,
        approval_ttl_seconds=30,
    )
    service = VaultMemoryService(
        index,
        retriever=retriever,
        task_bridge=bridge,
        candidate_workflow=workflow,
    )
    context = MemoryTaskContext(
        task_id="task-memory",
        session_id="session-memory",
        correlation_id="correlation-memory",
        thread_id="thread-memory",
        turn_id="turn-memory",
    )
    index.rebuild()
    yield vault, workflow, service, task_store, trace_store, context
    service.close()
    task_store.close()
    trace_store.close()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Merke dir: Ich bevorzuge Python.", "Ich bevorzuge Python."),
        ("Bitte merken, kurze Antworten", "kurze Antworten"),
        ("Remember that the project is Apollo", "the project is Apollo"),
        ("Das ist nur eine normale Frage", None),
    ],
)
def test_remember_request_recognition(text: str, expected: str | None) -> None:
    assert recognize_memory_request(text) == expected


def test_candidate_never_writes_before_approval(candidate_runtime) -> None:
    vault, workflow, _service, task_store, _trace_store, context = candidate_runtime

    candidate = workflow.create(
        context,
        body="Ich bevorzuge Python.",
        note_type="preference",
        idempotency_key="candidate-1",
    )
    approval = task_store.get_approval(candidate.approval_id or "")

    assert candidate.status is CandidateStatus.PENDING_APPROVAL
    assert candidate.risk_level == 1
    assert candidate.before_hash is None
    assert candidate.expected_version == "absent"
    assert candidate.planned_diff.startswith("--- a/")
    assert list(vault.rglob("*.md")) == []
    assert approval is not None
    assert approval.status is ApprovalStatus.PENDING
    assert approval.kind is ApprovalKind.FILE_CHANGE
    assert approval.sandbox == "workspace_write"
    assert approval.payload["allow_once_only"] is True


def test_allow_once_applies_atomic_write_and_updates_index(
    candidate_runtime,
) -> None:
    vault, workflow, _service, task_store, trace_store, context = candidate_runtime
    candidate = workflow.create(
        context,
        body="Ich bevorzuge Python.",
        note_type="preference",
        correction=True,
        idempotency_key="candidate-allow",
    )

    applied = workflow.decide(
        candidate.candidate_id,
        allow=True,
        decision_id="allow-once-1",
    )
    note = workflow.index.get_note(candidate.note_id)
    events = task_store.list_task_events(context.task_id)
    trace_events = trace_store.list_task_events(context.task_id)

    assert applied.status is CandidateStatus.APPLIED
    assert applied.write_operation_id is not None
    assert (vault / candidate.proposed_path).is_file()
    assert note is not None
    assert note.note_id == candidate.note_id
    assert note.source == "user_correction"
    assert {
        "memory.write_candidate_created",
        "memory.write_approved",
        "memory.write_applied",
        "memory.index_updated",
    } <= {event.event_type for event in events}
    assert any(
        event["event_type"] == "memory.write_applied" for event in trace_events
    )


def test_deny_writes_nothing_and_records_rejection(candidate_runtime) -> None:
    vault, workflow, _service, task_store, _trace_store, context = candidate_runtime
    candidate = workflow.create(
        context,
        body="Do not persist without consent.",
        idempotency_key="candidate-deny",
    )

    rejected = workflow.decide(
        candidate.candidate_id,
        allow=False,
        decision_id="deny-once-1",
    )

    assert rejected.status is CandidateStatus.REJECTED
    assert not (vault / candidate.proposed_path).exists()
    assert task_store.get_approval(candidate.approval_id or "").status is (
        ApprovalStatus.DENIED
    )
    assert any(
        event.event_type == "memory.write_rejected"
        for event in task_store.list_task_events(context.task_id)
    )


def test_approval_timeout_writes_nothing(candidate_runtime) -> None:
    vault, workflow, _service, task_store, _trace_store, context = candidate_runtime
    candidate = workflow.create(
        context,
        body="Timeout candidate.",
        idempotency_key="candidate-timeout",
    )

    expired = workflow.expire(
        candidate.candidate_id,
        decision_id="timeout-candidate",
    )

    assert expired.status is CandidateStatus.EXPIRED
    assert not (vault / candidate.proposed_path).exists()
    assert task_store.get_approval(candidate.approval_id or "").status is (
        ApprovalStatus.EXPIRED
    )


def test_candidate_create_is_idempotent(candidate_runtime) -> None:
    _vault, workflow, _service, task_store, _trace_store, context = candidate_runtime
    first = workflow.create(
        context,
        body="One candidate only.",
        idempotency_key="same-key",
    )
    repeated = workflow.create(
        context,
        body="One candidate only.",
        idempotency_key="same-key",
    )

    assert repeated == first
    assert len(workflow.list()) == 1
    assert len(task_store.list_pending_approvals(task_id=context.task_id)) == 1


def test_repeated_apply_does_not_execute_twice(candidate_runtime) -> None:
    _vault, workflow, _service, _task_store, _trace_store, context = (
        candidate_runtime
    )
    candidate = workflow.create(
        context,
        body="Exactly once.",
        idempotency_key="candidate-exact-once",
    )
    first = workflow.decide(
        candidate.candidate_id,
        allow=True,
        decision_id="allow-exact-once",
    )

    repeated = workflow.apply(candidate.candidate_id)
    operation_count = workflow.index.connection.execute(
        "SELECT COUNT(*) FROM memory_write_operations"
    ).fetchone()[0]

    assert repeated.write_operation_id == first.write_operation_id
    assert operation_count == 1


def test_external_create_after_approval_stops_write(candidate_runtime) -> None:
    vault, workflow, _service, task_store, _trace_store, context = candidate_runtime
    candidate = workflow.create(
        context,
        body="Candidate content.",
        idempotency_key="candidate-conflict",
    )
    task_store.decide_approval(
        candidate.approval_id or "",
        allow=True,
        decision_id="allow-before-external-change",
    )
    target = vault / candidate.proposed_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("external content\n", encoding="utf-8")

    with pytest.raises(ConcurrentMemoryWrite):
        workflow.apply(candidate.candidate_id)

    conflicted = workflow.get(candidate.candidate_id)
    assert conflicted is not None
    assert conflicted.status is CandidateStatus.CONFLICTED
    assert conflicted.conflict_state is ConflictState.EXTERNALLY_MODIFIED
    assert target.read_text(encoding="utf-8") == "external content\n"
    assert workflow.list_conflicts()[0].state is (
        ConflictState.EXTERNALLY_MODIFIED
    )


def test_duplicate_candidate_is_visible_and_not_automatic(candidate_runtime) -> None:
    vault, workflow, _service, _task_store, _trace_store, context = (
        candidate_runtime
    )
    _existing_note(vault / "existing.md", body="Same durable fact.")
    workflow.index.sync()

    candidate = workflow.create(
        context,
        body="Same durable fact.",
        idempotency_key="candidate-duplicate",
    )

    assert candidate.conflict_state is ConflictState.DUPLICATE
    assert candidate.status is CandidateStatus.PENDING_APPROVAL
    assert not (vault / candidate.proposed_path).exists()
    assert workflow.list_conflicts()[0].state is ConflictState.DUPLICATE


def test_user_correction_conflict_is_visible_and_resolvable(
    candidate_runtime,
) -> None:
    vault, workflow, _service, _task_store, _trace_store, context = (
        candidate_runtime
    )
    old_id = _existing_note(
        vault / "graz.md",
        body="Ich wohne in Graz.",
        source="inferred",
        conflict_key="residence",
    )
    workflow.index.sync()

    candidate = workflow.create(
        context,
        body="Ich wohne in Wien.",
        correction=True,
        conflict_key="residence",
        idempotency_key="candidate-correction",
    )
    conflict = next(
        item
        for item in workflow.list_conflicts()
        if item.candidate_id == candidate.candidate_id
    )
    resolved = workflow.resolve_conflict(
        conflict.conflict_id,
        winner_note_id=candidate.note_id,
        resolution="direct current user correction has priority",
    )

    assert candidate.conflict_state is ConflictState.CONFIRMED_CONFLICT
    assert old_id in conflict.note_ids
    assert resolved.winner_note_id == candidate.note_id
    assert resolved.state is ConflictState.NONE
    assert resolved.resolved_at is not None


def test_restore_path_removes_new_note_and_rebuilds_index(candidate_runtime) -> None:
    vault, workflow, _service, _task_store, _trace_store, context = (
        candidate_runtime
    )
    candidate = workflow.create(
        context,
        body="Restore-test fact.",
        idempotency_key="candidate-restore",
    )
    applied = workflow.decide(
        candidate.candidate_id,
        allow=True,
        decision_id="allow-restore",
    )

    restored_hash = workflow.restore_write(applied.write_operation_id or "")

    assert restored_hash is None
    assert not (vault / candidate.proposed_path).exists()
    assert workflow.index.get_note(candidate.note_id) is None
    row = workflow.index.connection.execute(
        "SELECT status FROM memory_write_operations WHERE operation_id=?",
        (applied.write_operation_id,),
    ).fetchone()
    assert row["status"] == "restored"


def test_read_only_mode_refuses_even_approved_candidate(
    candidate_runtime,
) -> None:
    _vault, workflow, _service, task_store, _trace_store, context = candidate_runtime
    candidate = workflow.create(
        context,
        body="Read-only must win.",
        idempotency_key="candidate-read-only",
    )
    task_store.decide_approval(
        candidate.approval_id or "",
        allow=True,
        decision_id="allow-but-read-only",
    )
    workflow.index.mode = "read-only"

    with pytest.raises(PermissionError, match="writable-test"):
        workflow.apply(candidate.candidate_id)
