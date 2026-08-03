"""Flow memory writes and non-blocking proposal tests in a synthetic vault."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from pathlib import Path

import pytest

from openjarvis.flow import FlowSessionAuthority
from openjarvis.memory.candidates import (
    MemoryCandidateWorkflow,
    has_memory_intent,
    recognize_memory_request,
)
from openjarvis.memory.safe_write import AtomicMarkdownWriter, ConcurrentMemoryWrite
from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import CandidateStatus, ConflictState
from openjarvis.memory.vault_retrieval import VaultRetriever
from openjarvis.memory.vault_service import VaultMemoryService
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import ExecutionLane
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


def _activate_flow(workflow: MemoryCandidateWorkflow) -> FlowSessionAuthority:
    secret = "f" * 64
    now = 1_800_000_000
    nonce = uuid.uuid4().hex
    owner = "memory-test-owner"
    message = f"flow-v1\n{nonce}\n{now}\n{owner}".encode()
    authority = FlowSessionAuthority(secret, clock=lambda: now)
    authority.activate_flow(
        nonce=nonce,
        authenticated_at=now,
        signature=hmac.new(secret.encode(), message, hashlib.sha256).hexdigest(),
        owner=owner,
    )
    workflow.flow_authority = authority
    return authority


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
        ("Merk dir, dass ich kurze Antworten mag.", "dass ich kurze Antworten mag."),
        ("Bitte merken, kurze Antworten", "kurze Antworten"),
        ("Remember that the project is Apollo", "the project is Apollo"),
        ("Ich heiße Bashar, merk dir das.", "Ich heiße Bashar"),
        ("Du sollst dir merken, dass ich Bashar heiße.", "dass ich Bashar heiße."),
        ("Behalte im Gedächtnis: Ich arbeite nachts.", "Ich arbeite nachts."),
        ("Lies ppx.at aus und merk dir alles dort.", None),
        ("Das ist nur eine normale Frage", None),
    ],
)
def test_remember_request_recognition(text: str, expected: str | None) -> None:
    assert recognize_memory_request(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Lies ppx.at aus und merk dir alles dort.",
        "Ich möchte, dass du dir meine Arbeitszeiten merkst.",
        "Das Ergebnis dauerhaft speichern.",
    ],
)
def test_semantic_memory_intent_recognition(text: str) -> None:
    assert has_memory_intent(text)


def test_memory_retrieval_question_is_not_a_write_intent() -> None:
    assert not has_memory_intent("Was hast du dir über mich gemerkt?")


def test_non_flow_candidate_is_a_non_blocking_proposal(candidate_runtime) -> None:
    vault, workflow, _service, task_store, _trace_store, context = candidate_runtime

    candidate = workflow.create(
        context,
        body="Ich bevorzuge Python.",
        note_type="preference",
        idempotency_key="candidate-1",
    )
    assert candidate.status is CandidateStatus.PROPOSED
    assert candidate.risk_level == 1
    assert candidate.before_hash is None
    assert candidate.expected_version == "absent"
    assert candidate.planned_diff.startswith("--- a/")
    assert list(vault.rglob("*.md")) == []
    assert candidate.approval_id is None
    assert task_store.list_pending_approvals(task_id=context.task_id) == []


def test_flow_applies_atomic_write_directly_and_updates_index(
    candidate_runtime,
) -> None:
    vault, workflow, _service, task_store, trace_store, context = candidate_runtime
    _activate_flow(workflow)
    applied = workflow.create(
        context,
        body="Ich bevorzuge Python.",
        note_type="preference",
        correction=True,
        idempotency_key="candidate-flow-direct",
    )
    note = workflow.index.get_note(applied.note_id)
    events = task_store.list_task_events(context.task_id)
    trace_events = trace_store.list_task_events(context.task_id)

    assert applied.status is CandidateStatus.APPLIED
    assert applied.approval_id is None
    assert applied.write_operation_id is not None
    assert (vault / applied.proposed_path).is_file()
    assert note is not None
    assert note.note_id == applied.note_id
    assert note.source == "user_correction"
    assert {
        "memory.write_candidate_created",
        "memory.write_applied",
        "memory.index_updated",
    } <= {event.event_type for event in events}
    assert task_store.list_pending_approvals(task_id=context.task_id) == []
    assert any(
        event["event_type"] == "memory.write_applied" for event in trace_events
    )


def test_proposal_cannot_be_applied_without_flow(candidate_runtime) -> None:
    vault, workflow, _service, _task_store, _trace_store, context = candidate_runtime
    candidate = workflow.create(
        context,
        body="Do not persist outside Flow.",
        idempotency_key="candidate-no-flow",
    )

    with pytest.raises(PermissionError, match="active Flow"):
        workflow.apply(candidate.candidate_id)

    assert not (vault / candidate.proposed_path).exists()


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
    assert task_store.list_pending_approvals(task_id=context.task_id) == []


def test_repeated_apply_does_not_execute_twice(candidate_runtime) -> None:
    _vault, workflow, _service, _task_store, _trace_store, context = (
        candidate_runtime
    )
    _activate_flow(workflow)
    first = workflow.create(
        context,
        body="Exactly once.",
        idempotency_key="candidate-exact-once",
    )

    repeated = workflow.apply(first.candidate_id)
    operation_count = workflow.index.connection.execute(
        "SELECT COUNT(*) FROM memory_write_operations"
    ).fetchone()[0]

    assert repeated.write_operation_id == first.write_operation_id
    assert operation_count == 1


def test_external_create_before_flow_write_stops_write(candidate_runtime) -> None:
    vault, workflow, _service, _task_store, _trace_store, context = (
        candidate_runtime
    )
    candidate = workflow.create(
        context,
        body="Candidate content.",
        idempotency_key="candidate-conflict",
    )
    _activate_flow(workflow)
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
    assert candidate.status is CandidateStatus.PROPOSED
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
    _activate_flow(workflow)
    applied = workflow.create(
        context,
        body="Restore-test fact.",
        idempotency_key="candidate-restore",
    )

    restored_hash = workflow.restore_write(applied.write_operation_id or "")

    assert restored_hash is None
    assert not (vault / applied.proposed_path).exists()
    assert workflow.index.get_note(applied.note_id) is None
    row = workflow.index.connection.execute(
        "SELECT status FROM memory_write_operations WHERE operation_id=?",
        (applied.write_operation_id,),
    ).fetchone()
    assert row["status"] == "restored"


def test_flow_write_is_not_blocked_by_legacy_read_only_vault_mode(
    candidate_runtime,
) -> None:
    vault, workflow, _service, _task_store, _trace_store, context = candidate_runtime
    candidate = workflow.create(
        context,
        body="Flow authority wins over the legacy vault flag.",
        idempotency_key="candidate-flow-overrides-read-only",
    )
    workflow.index.mode = "read-only"
    _activate_flow(workflow)

    applied = workflow.apply(candidate.candidate_id)

    assert applied.status is CandidateStatus.APPLIED
    assert (vault / candidate.proposed_path).is_file()
