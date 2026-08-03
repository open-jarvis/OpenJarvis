"""Local API tests for vault search, sources, and direct Flow writes."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.flow import FlowSessionAuthority
from openjarvis.memory.candidates import MemoryCandidateWorkflow
from openjarvis.memory.safe_write import AtomicMarkdownWriter
from openjarvis.memory.task_bridge import MemoryTaskBridge
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_retrieval import VaultRetriever
from openjarvis.memory.vault_service import VaultMemoryService
from openjarvis.server.auth_middleware import AuthMiddleware
from openjarvis.server.memory_vault_routes import router as memory_router
from openjarvis.server.task_routes import router as task_router
from openjarvis.tasks.service import TaskService
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import ExecutionLane
from openjarvis.traces.store import TraceStore


def _note(
    path: Path,
    *,
    title: str,
    body: str,
    note_type: str = "fact",
    status: str = "active",
    scope: str = "personal",
    project: str | None = None,
    extra: str = "",
) -> str:
    note_id = str(uuid.uuid4())
    project_line = f"project: {project}\n" if project is not None else ""
    path.write_text(
        "---\n"
        f"id: {note_id}\n"
        "schema_version: 1\n"
        f"type: {note_type}\n"
        f"status: {status}\n"
        f"scope: {scope}\n"
        f"{project_line}"
        "source: manual\n"
        f"title: {title}\n"
        f"{extra}"
        "---\n"
        f"{body.rstrip()}\n",
        encoding="utf-8",
    )
    return note_id


@pytest.fixture()
def api_runtime(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    task_store = TaskStore(tmp_path / "tasks.sqlite3")
    task_service = TaskService(task_store)
    trace_store = TraceStore(tmp_path / "traces.sqlite3")
    task_store.create_task(
        task_id="task-api",
        session_id="session-api",
        correlation_id="correlation-api",
        description="Memory API test",
        execution_lane=ExecutionLane.MODEL,
        backend="codex",
        risk_level=1,
        component="test",
        cause="user_request",
        idempotency_key="create-api-task",
    )
    index = VaultIndex(
        vault,
        tmp_path / "state" / "memory.sqlite3",
        mode="writable-test",
    )
    retriever = VaultRetriever(index)
    bridge = MemoryTaskBridge(task_store, trace_store=trace_store)
    secret = "f" * 64
    now = 1_800_000_000
    nonce = "memory-api-native-proof"
    owner = "memory-api-owner"
    message = f"flow-v1\n{nonce}\n{now}\n{owner}".encode()
    authority = FlowSessionAuthority(secret, clock=lambda: now)
    authority.activate_flow(
        nonce=nonce,
        authenticated_at=now,
        signature=hmac.new(secret.encode(), message, hashlib.sha256).hexdigest(),
        owner=owner,
    )
    workflow = MemoryCandidateWorkflow(
        index,
        retriever,
        bridge,
        AtomicMarkdownWriter(vault, tmp_path / "restore"),
        flow_authority=authority,
    )
    service = VaultMemoryService(
        index,
        retriever=retriever,
        task_bridge=bridge,
        candidate_workflow=workflow,
    )
    app = FastAPI()
    app.state.flow_authority = authority
    app.state.vault_memory_service = service
    app.state.task_store = task_store
    app.state.task_service = task_service
    app.include_router(memory_router)
    app.include_router(task_router)
    client = TestClient(app)
    headers = {
        "X-Task-ID": "task-api",
        "X-Session-ID": "session-api",
        "X-Correlation-ID": "correlation-api",
        "X-Thread-ID": "thread-api",
        "X-Turn-ID": "turn-api",
    }
    yield vault, service, workflow, task_store, client, headers
    client.close()
    service.close()
    task_store.close()
    trace_store.close()


def test_health_is_privacy_safe_and_search_returns_exact_sources(
    api_runtime,
) -> None:
    vault, service, _workflow, _task_store, client, headers = api_runtime
    note_id = _note(
        vault / "python.md",
        title="Python Preference",
        body="The user prefers Python.",
    )
    service.rebuild()

    health = client.get("/v1/memory/health")
    search = client.get(
        "/v1/memory/search",
        params={"query": "prefers Python"},
        headers=headers,
    )

    assert health.status_code == 200
    assert health.json()["note_count"] == 1
    assert "vault_root" not in health.text
    assert "The user prefers Python" not in health.text
    assert search.status_code == 200
    payload = search.json()
    assert payload["evidence_status"] == "sufficient"
    assert payload["selected_sources"][0]["note_id"] == note_id
    assert payload["selected_sources"][0]["path"] == "python.md"
    assert payload["selected_sources"][0]["retrieval_class"] == "normal"
    assert payload["retrieval_purpose"] == "normal"


def test_sensitive_and_structural_notes_require_separate_explicit_endpoints(
    api_runtime,
) -> None:
    vault, service, _workflow, _task_store, client, headers = api_runtime
    policy_id = _note(
        vault / "policy.md",
        title="Synthetic Policy",
        body="Unique authority boundary policy token.",
        note_type="system_policy",
        extra="trust_class: trusted\nauthority_class: runtime\n",
    )
    category_id = _note(
        vault / "category.md",
        title="Synthetic Category",
        body="Unique taxonomy boundary category token.",
        note_type="category",
    )
    service.rebuild()

    normal_policy = client.get(
        "/v1/memory/search",
        params={"query": "authority boundary", "note_type": "system_policy"},
        headers=headers,
    )
    review_policy = client.get(
        "/v1/memory/review/search",
        params={"query": "authority boundary", "note_type": "system_policy"},
    )
    normal_category = client.get(
        "/v1/memory/search",
        params={"query": "taxonomy boundary", "note_type": "category"},
        headers=headers,
    )
    structure_category = client.get(
        "/v1/memory/structure/search",
        params={"query": "taxonomy boundary", "note_type": "category"},
    )

    assert normal_policy.status_code == 200
    assert normal_policy.json()["selected_sources"] == []
    assert review_policy.status_code == 200
    assert review_policy.json()["retrieval_purpose"] == "explicit_review"
    assert review_policy.json()["selected_sources"][0]["note_id"] == policy_id
    assert review_policy.json()["selected_sources"][0]["authority_class"] == (
        "prohibited_runtime_authority"
    )
    assert normal_category.json()["selected_sources"] == []
    assert structure_category.json()["retrieval_purpose"] == "vault_structure"
    assert structure_category.json()["selected_sources"][0]["note_id"] == (category_id)


def test_project_profile_api_requires_exact_project_scope(api_runtime) -> None:
    vault, service, _workflow, _task_store, client, headers = api_runtime
    note_id = _note(
        vault / "project.md",
        title="Project Alpha",
        body="Unique exact project scope token.",
        note_type="project_profile",
        scope="Project-Alpha",
    )
    service.rebuild()

    missing = client.get(
        "/v1/memory/search",
        params={"query": "exact project scope"},
        headers=headers,
    )
    wrong = client.get(
        "/v1/memory/search",
        params={"query": "exact project scope", "project": "project-alpha"},
        headers=headers,
    )
    exact = client.get(
        "/v1/memory/search",
        params={"query": "exact project scope", "project": "Project-Alpha"},
        headers=headers,
    )

    assert missing.json()["selected_sources"] == []
    assert wrong.json()["selected_sources"] == []
    assert exact.json()["selected_sources"][0]["note_id"] == note_id
    assert exact.json()["selected_sources"][0]["scope_class"] == "exact_project"


def test_health_and_note_api_report_derived_status_without_honoring_overrides(
    api_runtime,
) -> None:
    vault, service, _workflow, _task_store, client, _headers = api_runtime
    note_id = _note(
        vault / "proposal.md",
        title="Proposal",
        body="Review-only proposal.",
        note_type="memory_proposal",
        status="proposed",
        extra="retrieval_class: normal\nauthority_class: runtime\n",
    )
    service.rebuild()

    health = client.get("/v1/memory/health").json()
    note = client.get(f"/v1/memory/notes/{note_id}").json()

    assert health["discovered_count"] == 1
    assert health["schema_valid_count"] == 1
    assert health["type_supported_count"] == 1
    assert health["fts_document_count"] == 1
    assert health["retrieval_eligible_count"] == 0
    assert health["review_only_count"] == 1
    assert note["note_type"] == "memory_proposal"
    assert note["trust_class"] == "untrusted_proposal"
    assert note["retrieval_class"] == "review_only"
    assert note["authority_class"] == "none"
    assert note["parse_status"] == "valid"
    assert note["retrieval_eligible"] is False


def test_note_links_graph_and_task_sources_endpoints(api_runtime) -> None:
    vault, service, _workflow, _task_store, client, headers = api_runtime
    target_id = _note(vault / "target.md", title="Target", body="Target body.")
    source_id = _note(
        vault / "source.md",
        title="Source",
        body="Target evidence and [[Target]].",
    )
    service.rebuild()
    client.get(
        "/v1/memory/search",
        params={"query": "Target evidence"},
        headers=headers,
    )

    note = client.get(f"/v1/memory/notes/{source_id}")
    links = client.get(f"/v1/memory/notes/{source_id}/links")
    graph = client.get("/v1/memory/graph")
    sources = client.get("/v1/tasks/task-api/sources")

    assert note.status_code == 200
    assert note.json()["note_id"] == source_id
    assert links.json()["outgoing"][0]["target_note_id"] == target_id
    assert {node["id"] for node in graph.json()["nodes"]} == {
        source_id,
        target_id,
    }
    assert sources.status_code == 200
    assert sources.json()["count"] >= 1
    assert all(
        item["source_kind"] == "memory_note" for item in sources.json()["sources"]
    )


def test_search_requires_canonical_task_headers(api_runtime) -> None:
    _vault, _service, _workflow, _task_store, client, _headers = api_runtime

    response = client.get("/v1/memory/search", params={"query": "Python"})

    assert response.status_code == 422


def test_reindex_is_idempotent_and_does_not_write_markdown(api_runtime) -> None:
    vault, _service, _workflow, _task_store, client, headers = api_runtime
    _note(vault / "note.md", title="Note", body="Body.")
    mutation_headers = {**headers, "Idempotency-Key": "reindex-1"}
    before = (vault / "note.md").read_bytes()

    first = client.post("/v1/memory/reindex", headers=mutation_headers)
    repeated = client.post("/v1/memory/reindex", headers=mutation_headers)

    assert first.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert repeated.status_code == 200
    assert repeated.json()["idempotent_replay"] is True
    assert first.json()["run_id"] == repeated.json()["run_id"]
    assert (vault / "note.md").read_bytes() == before


def test_candidate_create_writes_directly_in_flow(api_runtime) -> None:
    vault, _service, _workflow, _task_store, client, headers = api_runtime
    create_headers = {**headers, "Idempotency-Key": "candidate-api-create"}

    created = client.post(
        "/v1/memory/candidates",
        headers=create_headers,
        json={
            "body": "Ich bevorzuge Python.",
            "note_type": "preference",
            "correction": True,
        },
    )
    candidate = created.json()

    assert created.status_code == 201
    assert candidate["status"] == "applied"
    assert candidate["approval_id"] is None
    assert (vault / candidate["proposed_path"]).is_file()


def test_candidate_create_is_blocked_outside_flow(api_runtime) -> None:
    vault, _service, workflow, _task_store, client, headers = api_runtime
    client.app.state.flow_authority.activate_assistant()

    response = client.post(
        "/v1/memory/candidates",
        headers={**headers, "Idempotency-Key": "candidate-api-assistant"},
        json={"body": "Assistant must not write memory."},
    )

    assert response.status_code == 403
    assert workflow.list() == []
    assert list(vault.rglob("*.md")) == []


def test_memory_allow_once_endpoints_are_removed(api_runtime) -> None:
    _vault, _service, _workflow, _task_store, client, headers = api_runtime
    created = client.post(
        "/v1/memory/candidates",
        headers={**headers, "Idempotency-Key": "candidate-api-reject-create"},
        json={"body": "Direct Flow memory."},
    ).json()

    approved = client.post(
        f"/v1/memory/candidates/{created['candidate_id']}/approve",
        headers={**headers, "Idempotency-Key": "obsolete-memory-approve"},
    )
    rejected = client.post(
        f"/v1/memory/candidates/{created['candidate_id']}/reject",
        headers={**headers, "Idempotency-Key": "obsolete-memory-reject"},
    )

    assert approved.status_code == 404
    assert rejected.status_code == 404


def test_api_cannot_turn_legacy_source_type_into_a_memory_candidate(
    api_runtime,
) -> None:
    _vault, _service, workflow, _task_store, client, headers = api_runtime

    response = client.post(
        "/v1/memory/candidates",
        headers={**headers, "Idempotency-Key": "no-proposal-elevation"},
        json={
            "body": "A parsed proposal is not a confirmed memory.",
            "note_type": "memory_proposal",
        },
    )

    assert response.status_code == 422
    assert workflow.list() == []


def test_candidate_api_create_is_idempotent(api_runtime) -> None:
    _vault, _service, workflow, _task_store, client, headers = api_runtime
    mutation_headers = {**headers, "Idempotency-Key": "candidate-api-same"}
    payload = {"body": "One API candidate."}

    first = client.post(
        "/v1/memory/candidates",
        headers=mutation_headers,
        json=payload,
    )
    repeated = client.post(
        "/v1/memory/candidates",
        headers=mutation_headers,
        json=payload,
    )

    assert first.status_code == repeated.status_code == 201
    assert first.json()["candidate_id"] == repeated.json()["candidate_id"]
    assert len(workflow.list()) == 1


def test_unconfigured_health_does_not_create_a_vault(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(memory_router)
    client = TestClient(app)

    response = client.get("/v1/memory/health")

    assert response.status_code == 200
    assert response.json()["vault_configured"] is False
    assert list(tmp_path.iterdir()) == []
    client.close()


def test_auth_middleware_protects_memory_api(api_runtime) -> None:
    _vault, service, _workflow, task_store, _client, _headers = api_runtime
    app = FastAPI()
    app.state.vault_memory_service = service
    app.state.task_store = task_store
    app.state.task_service = TaskService(task_store)
    app.include_router(memory_router)
    app.add_middleware(AuthMiddleware, api_key="test-secret")
    client = TestClient(app)

    denied = client.get("/v1/memory/health")
    allowed = client.get(
        "/v1/memory/health",
        headers={"Authorization": "Bearer test-secret"},
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    client.close()
