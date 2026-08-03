"""Integration tests for the local canonical task and approval API."""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.codex.store import (  # noqa: E402
    CodexThreadRecord,
    CodexTurnRecord,
)
from openjarvis.codex.types import (  # noqa: E402
    ApprovalMode,
    BackendCapabilities,
    CodexBackendError,
    CodexBackendKind,
    CodexHealth,
    SandboxMode,
)
from openjarvis.core.config import JarvisConfig  # noqa: E402
from openjarvis.core.events import EventBus  # noqa: E402
from openjarvis.flow import FlowSessionAuthority  # noqa: E402
from openjarvis.memory.candidates import MemoryCandidateWorkflow  # noqa: E402
from openjarvis.memory.safe_write import AtomicMarkdownWriter  # noqa: E402
from openjarvis.memory.task_bridge import MemoryTaskBridge  # noqa: E402
from openjarvis.memory.vault_index import VaultIndex  # noqa: E402
from openjarvis.memory.vault_retrieval import VaultRetriever  # noqa: E402
from openjarvis.memory.vault_service import VaultMemoryService  # noqa: E402
from openjarvis.server.app import create_app  # noqa: E402
from openjarvis.server.task_routes import (  # noqa: E402
    _parse_tool_proposal,
)
from openjarvis.server.task_routes import (  # noqa: E402
    router as task_router,
)
from openjarvis.tasks.orchestrator import TaskExecutionResult  # noqa: E402
from openjarvis.tasks.policy import RiskLevel  # noqa: E402
from openjarvis.tasks.service import TaskService  # noqa: E402
from openjarvis.tasks.store import TaskStore  # noqa: E402
from openjarvis.tasks.types import TaskOutcome, TaskStatus  # noqa: E402
from openjarvis.tools.actions import ActionStatus, VerificationStatus  # noqa: E402
from openjarvis.tools.manifest import SideEffectClass  # noqa: E402

_HEADERS = {
    "X-Correlation-ID": "api-correlation",
    "Idempotency-Key": "api-idempotency",
}
_CAPABILITIES = BackendCapabilities(
    persistent_threads=True,
    resume=True,
    fork=True,
    streaming=True,
    steer=True,
    interrupt=True,
    command_approvals=True,
    file_approvals=True,
    full_item_events=True,
    usage_events=True,
    read_only=True,
    workspace_write=True,
)


class FakeOrchestrator:
    def __init__(self, service: TaskService) -> None:
        self.service = service
        self.execute_count = 0
        self.last_execute_kwargs = {}

    async def health(self):
        return (
            CodexHealth(
                available=True,
                authenticated=True,
                auth_mode="chatgpt",
                runtime_version="test-runtime",
                backend=CodexBackendKind.PYTHON_SDK,
                capabilities=_CAPABILITIES,
                detail="authorization=super-secret",
            ),
            CodexHealth(
                available=True,
                authenticated=True,
                auth_mode="chatgpt",
                runtime_version="test-runtime",
                backend=CodexBackendKind.APP_SERVER,
                capabilities=_CAPABILITIES,
            ),
        )

    async def execute(
        self,
        task_id: str,
        prompt: str,
        **kwargs,
    ) -> TaskExecutionResult:
        del prompt
        self.last_execute_kwargs = kwargs
        self.execute_count += 1
        current = self.service.get(task_id)
        assert current is not None
        if current.status in {
            TaskStatus.PENDING,
            TaskStatus.PAUSED,
            TaskStatus.RECOVERING,
        }:
            current = self.service.transition(
                task_id,
                TaskStatus.RUNNING,
                component="fake_codex",
                cause="fake_turn_started",
                idempotency_key=f"fake-run:{self.execute_count}",
                active_thread_id="thread-secret-value",
                active_turn_id="turn-secret-value",
            )
        return TaskExecutionResult(
            task=current,
            content="fake result",
            thread_id="thread-secret-value",
            turn_id="turn-secret-value",
        )

    async def pause(self, task_id: str, *, cause: str, idempotency_key: str):
        return self.service.transition(
            task_id,
            TaskStatus.PAUSED,
            component="task_api",
            cause=cause,
            idempotency_key=idempotency_key,
        )

    async def cancel(self, task_id: str, *, cause: str, idempotency_key: str):
        return self.service.transition(
            task_id,
            TaskStatus.CANCELED,
            component="task_api",
            cause=cause,
            idempotency_key=idempotency_key,
            outcome=TaskOutcome.CANCELED,
        )


@pytest.fixture
def api_runtime(tmp_path: Path):
    store = TaskStore(tmp_path / "tasks.db")
    service = TaskService(store)
    orchestrator = FakeOrchestrator(service)
    secret = "f" * 64
    authenticated_at = int(time.time())
    nonce = "task-routes-native-proof"
    owner = "test-owner"
    message = f"flow-v1\n{nonce}\n{authenticated_at}\n{owner}".encode()
    authority = FlowSessionAuthority(secret)
    authority.activate_flow(
        nonce=nonce,
        authenticated_at=authenticated_at,
        signature=hmac.new(secret.encode(), message, hashlib.sha256).hexdigest(),
        owner=owner,
    )

    app = FastAPI()
    app.state.task_store = store
    app.state.task_service = service
    app.state.flow_authority = authority
    app.state.codex_orchestrator = orchestrator
    assistant_workspace = tmp_path / "assistant-workspace"
    assistant_workspace.mkdir()
    app.state.assistant_workspace = assistant_workspace
    app.state.config = SimpleNamespace(
        sandbox=SimpleNamespace(workspace=str(assistant_workspace)),
        codex=SimpleNamespace(
            analysis_sandbox="read_only",
            approval_mode="deny_all",
            allow_cli_fallback=False,
        ),
    )
    vault = tmp_path / "memory-vault"
    vault.mkdir()
    memory_index = VaultIndex(
        vault,
        tmp_path / "memory-state" / "index.sqlite3",
        mode="read-only",
    )
    memory_retriever = VaultRetriever(memory_index)
    memory_bridge = MemoryTaskBridge(store)
    memory_workflow = MemoryCandidateWorkflow(
        memory_index,
        memory_retriever,
        memory_bridge,
        AtomicMarkdownWriter(vault, tmp_path / "memory-restore"),
        flow_authority=authority,
    )
    memory_service = VaultMemoryService(
        memory_index,
        retriever=memory_retriever,
        task_bridge=memory_bridge,
        candidate_workflow=memory_workflow,
    )
    memory_index.rebuild()
    app.state.vault_memory_service = memory_service
    app.include_router(task_router)
    try:
        yield TestClient(app), store, service, memory_service, orchestrator
    finally:
        memory_service.close()
        store.close()


def _create(client: TestClient, **body):
    payload = {"description": "Inspect the isolated test workspace", **body}
    return client.post("/v1/tasks", json=payload, headers=_HEADERS)


def _chat(
    client: TestClient,
    *,
    message: str = "Inspect the synthetic workspace",
    session_id: str = "session-chat",
    task_id: str = "task-chat",
    correlation_id: str = "chat-correlation",
    idempotency_key: str = "chat-message-once",
    input_mode: str = "text",
):
    return client.post(
        "/v1/chat",
        json={
            "message": message,
            "session_id": session_id,
            "task_id": task_id,
            "input_mode": input_mode,
            "use_memory": False,
        },
        headers={
            "X-Correlation-ID": correlation_id,
            "Idempotency-Key": idempotency_key,
        },
    )


def test_mutations_require_correlation_and_idempotency(api_runtime) -> None:
    client, *_ = api_runtime
    response = client.post(
        "/v1/tasks",
        json={"description": "read only"},
    )
    assert response.status_code == 422


def test_create_read_list_and_timeline_are_correlated(api_runtime) -> None:
    client, *_ = api_runtime
    response = _create(client)
    assert response.status_code == 201
    task = response.json()
    assert task["correlation_id"] == "api-correlation"
    assert task["status"] == "pending"

    listed = client.get("/v1/tasks").json()
    assert listed["count"] == 1
    assert listed["tasks"][0]["task_id"] == task["task_id"]

    timeline = client.get(f"/v1/tasks/{task['task_id']}/timeline").json()
    assert timeline["events"][0]["event_type"] == "task.created"
    assert timeline["events"][0]["correlation_id"] == "api-correlation"


def test_chat_creates_canonical_task_and_persisted_messages(api_runtime) -> None:
    client, _, _, _, orchestrator = api_runtime

    response = _chat(client)

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["task_id"] == "task-chat"
    assert body["task"]["session_id"] == "session-chat"
    assert body["content"] == "fake result"
    assert orchestrator.execute_count == 1
    timeline = client.get("/v1/tasks/task-chat/timeline").json()["events"]
    assert [event["event_type"] for event in timeline] == [
        "task.created",
        "chat.user_message",
        "assistant.intent_classified",
        "task.state_changed",
        "chat.assistant_message",
    ]
    assert timeline[1]["payload"]["input_mode"] == "text"


def test_chat_idempotency_prevents_duplicate_turn(api_runtime) -> None:
    client, _, _, _, orchestrator = api_runtime

    first = _chat(client)
    replay = _chat(client)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["content"] == "fake result"
    assert orchestrator.execute_count == 1


def test_explicit_memory_command_writes_immediately_in_flow(api_runtime) -> None:
    client, store, _, memory_service, orchestrator = api_runtime

    response = _chat(
        client,
        message="Merk dir, dass ich kurze Antworten bevorzuge.",
        task_id="task-flow-memory",
        idempotency_key="flow-memory-once",
    )

    assert response.status_code == 200
    assert response.json()["content"] == (
        "Gespeichert: dass ich kurze Antworten bevorzuge."
    )
    assert orchestrator.execute_count == 0
    candidates = memory_service.candidate_workflow.list()
    assert len(candidates) == 1
    assert candidates[0].status.value == "applied"
    assert candidates[0].approval_id is None
    assert (memory_service.index.vault_root / candidates[0].proposed_path).is_file()
    assert store.list_pending_approvals(task_id="task-flow-memory") == []
    timeline = client.get("/v1/tasks/task-flow-memory/timeline").json()["events"]
    assert "memory.flow_write_applied" in {
        event["event_type"] for event in timeline
    }


def test_text_and_voice_use_same_task_and_voice_cannot_approve(api_runtime) -> None:
    client, store, _, _, orchestrator = api_runtime
    first = _chat(client)
    assert first.status_code == 200

    second = _chat(
        client,
        message="ja",
        correlation_id="voice-correlation",
        idempotency_key="voice-message-once",
        input_mode="voice",
    )

    assert second.status_code == 200
    assert second.json()["task"]["task_id"] == "task-chat"
    assert orchestrator.execute_count == 2
    timeline = client.get("/v1/tasks/task-chat/timeline").json()["events"]
    voice = [event for event in timeline if event["event_type"] == "chat.user_message"][
        -1
    ]
    assert voice["payload"]["input_mode"] == "voice"
    assert store.list_pending_approvals(task_id="task-chat") == []


def test_sessions_and_summary_are_canonical_projections(api_runtime) -> None:
    client, *_ = api_runtime
    assert _chat(client).status_code == 200

    sessions = client.get("/v1/sessions").json()
    assert sessions["count"] == 1
    assert sessions["sessions"][0]["session_id"] == "session-chat"
    detail = client.get("/v1/sessions/session-chat").json()
    assert detail["tasks"][0]["task_id"] == "task-chat"
    summary = client.get("/v1/tasks/task-chat/summary").json()
    assert summary["task"]["task_id"] == "task-chat"
    assert summary["last_sequence"] == 5
    assert summary["safe_to_present_as_success"] is False


def test_action_request_uses_trusted_workspace_and_code_owned_instructions(
    api_runtime,
) -> None:
    client, _, _, _, orchestrator = api_runtime
    response = _chat(
        client,
        message="Fix the bug in this repository and run the tests.",
        task_id="task-programming",
        idempotency_key="programming-once",
    )

    assert response.status_code == 200
    task = response.json()["task"]
    assert task["risk_level"] == 0
    kwargs = orchestrator.last_execute_kwargs
    assert kwargs["isolated_workspace"] is None
    assert kwargs["cwd"].name == "assistant-workspace"
    assert "do not request intermediate approvals" in (
        kwargs["developer_instructions"].lower()
    )
    assert "including commit or push" in kwargs["developer_instructions"].lower()
    timeline = client.get("/v1/tasks/task-programming/timeline").json()["events"]
    classified = next(
        event
        for event in timeline
        if event["event_type"] == "assistant.intent_classified"
    )
    assert classified["payload"] == {
        "authority": "code_owned",
        "kind": "programming",
        "reason": "programming_action",
        "risk_level": 0,
    }


def test_informational_browser_question_stays_read_only_chat(api_runtime) -> None:
    client, _, _, _, orchestrator = api_runtime

    response = _chat(
        client,
        message="Explain simply how a browser works.",
        task_id="task-browser-explanation",
        idempotency_key="browser-explanation-once",
    )

    assert response.status_code == 200
    assert response.json()["task"]["risk_level"] == 0
    instructions = orchestrator.last_execute_kwargs["developer_instructions"]
    assert "normally be answered directly" in instructions
    assert "Available tools:\n[]" in instructions
    timeline = client.get("/v1/tasks/task-browser-explanation/timeline").json()[
        "events"
    ]
    classified = next(
        event
        for event in timeline
        if event["event_type"] == "assistant.intent_classified"
    )
    assert classified["payload"]["kind"] == "chat"
    assert classified["payload"]["reason"] == "informational_chat"


def test_canonical_tool_proposal_parser_requires_one_exact_envelope() -> None:
    assert _parse_tool_proposal(
        '<openjarvis_tool_proposal>{"tool_id":"desktop.windows","arguments":{}}'
        "</openjarvis_tool_proposal>"
    ) == ("desktop.windows", {})
    assert (
        _parse_tool_proposal(
            'I will do it. <openjarvis_tool_proposal>{"tool_id":"desktop.windows",'
            '"arguments":{}}</openjarvis_tool_proposal>'
        )
        is None
    )


def test_tool_followup_uses_a_fresh_turn_correlation(api_runtime) -> None:
    client, _, service, _, orchestrator = api_runtime
    manifest = SimpleNamespace(
        tool_id="browser.windows",
        enabled=True,
        description="List browser windows",
        input_schema={"type": "object", "properties": {}},
        side_effect_class=SideEffectClass.LOCAL_READ,
        risk_level=RiskLevel.READ_ONLY,
        capability="browser:full",
        verification_strategy="verify",
        undo_strategy="none",
        timeout=20.0,
    )
    action = SimpleNamespace(
        action_id="action-browser-windows",
        tool_id="browser.windows",
        status=ActionStatus.VALIDATED,
        verification_status=VerificationStatus.PENDING,
        output_summary="",
        error="",
    )

    class FakeActionService:
        catalog = SimpleNamespace(list=lambda: (manifest,), get=lambda _tool_id: manifest)
        store = SimpleNamespace(list_actions=lambda _task_id: [])

        @staticmethod
        def runtime_available(_tool_id):
            return True

        @staticmethod
        def begin_task(_task_id):
            return None

        @staticmethod
        def create(_proposal):
            return action

        @staticmethod
        async def execute(_action_id):
            action.status = ActionStatus.COMPLETED
            action.verification_status = VerificationStatus.PASSED
            action.output_summary = '{"verified":true,"windows":[]}'
            return action

    client.app.state.tool_action_service = FakeActionService()
    calls: list[str] = []

    async def execute(task_id: str, prompt: str, **kwargs):
        del prompt
        calls.append(kwargs["turn_correlation_id"])
        current = service.get(task_id)
        assert current is not None
        if current.status is TaskStatus.PENDING:
            current = service.transition(
                task_id,
                TaskStatus.RUNNING,
                component="fake_codex",
                cause="fake_turn_started",
                idempotency_key="tool-loop-running",
                active_thread_id="thread-tool-loop",
                active_turn_id=f"turn-{len(calls)}",
            )
        content = (
            '<openjarvis_tool_proposal>{"tool_id":"browser.windows",'
            '"arguments":{}}</openjarvis_tool_proposal>'
            if len(calls) == 1
            else "Der Browserstatus wurde geprüft."
        )
        return TaskExecutionResult(
            task=current,
            content=content,
            thread_id="thread-tool-loop",
            turn_id=f"turn-{len(calls)}",
        )

    orchestrator.execute = execute
    response = _chat(
        client,
        message="Prüfe meine Browserfenster.",
        task_id="task-tool-loop",
        correlation_id="tool-turn",
        idempotency_key="tool-loop-once",
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Der Browserstatus wurde geprüft."
    assert calls == ["tool-turn", "tool-turn:tool-follow-up:1"]


def test_backend_turn_failure_keeps_chat_task_reusable(api_runtime) -> None:
    client, _, service, _, orchestrator = api_runtime

    async def failing_execute(task_id: str, prompt: str, **kwargs):
        del prompt, kwargs
        service.transition(
            task_id,
            TaskStatus.RUNNING,
            component="fake_codex",
            cause="fake_turn_started",
            idempotency_key="recoverable-running",
            active_thread_id="thread-recoverable",
        )
        service.transition(
            task_id,
            TaskStatus.FAILED,
            component="fake_codex",
            cause="fake_turn_failed",
            idempotency_key="recoverable-failed",
            outcome=TaskOutcome.FAILED,
            error_category="codex_backend_error",
        )
        raise CodexBackendError("synthetic backend failure")

    orchestrator.execute = failing_execute
    response = _chat(
        client,
        task_id="task-recoverable-chat",
        correlation_id="recoverable-turn",
        idempotency_key="recoverable-once",
    )

    assert response.status_code == 503
    task = service.get("task-recoverable-chat")
    assert task is not None and task.status is TaskStatus.RUNNING
    transitions = [
        event.status_to
        for event in service.timeline("task-recoverable-chat")
        if event.event_type == "task.state_changed"
    ]
    assert transitions[-2:] == [TaskStatus.RECOVERING, TaskStatus.RUNNING]
    assert (
        _parse_tool_proposal(
            '<openjarvis_tool_proposal>{"tool_id":"desktop.windows",'
            '"arguments":{},"risk_level":0}</openjarvis_tool_proposal>'
        )
        is None
    )


def test_chat_surfaces_usage_limit_without_raw_backend_message(api_runtime) -> None:
    client, _, service, _, orchestrator = api_runtime

    async def usage_limited_execute(task_id: str, prompt: str, **kwargs):
        del prompt, kwargs
        running = service.transition(
            task_id,
            TaskStatus.RUNNING,
            component="fake_codex",
            cause="fake_turn_started",
            idempotency_key="usage-limit-running",
            active_thread_id="thread-usage-limit",
        )
        event, _ = service.store.append_event(
            task_id=task_id,
            source_event_id="usage-limit-error",
            event_type="error",
            occurred_at=running.updated_at,
            cause="fake_backend_error",
            component="fake_codex",
            thread_id="thread-usage-limit",
            payload={
                "error": {
                    "codexErrorInfo": "usageLimitExceeded",
                    "message": "raw account-specific reset details",
                }
            },
        )
        service.project_committed(event)
        failed = service.transition(
            task_id,
            TaskStatus.FAILED,
            component="fake_codex",
            cause="fake_turn_failed",
            idempotency_key="usage-limit-failed",
            outcome=TaskOutcome.FAILED,
            error_category="codex_turn_failed",
            active_thread_id="thread-usage-limit",
        )
        return TaskExecutionResult(
            task=failed,
            content="",
            thread_id="thread-usage-limit",
            turn_id=None,
        )

    orchestrator.execute = usage_limited_execute
    response = _chat(
        client,
        message="Explain why the sky is blue.",
        task_id="task-usage-limited",
        idempotency_key="usage-limited-once",
    )

    assert response.status_code == 429
    assert response.json()["detail"] == (
        "Codex ChatGPT usage limit exceeded; no alternate backend was used."
    )
    assert "account-specific" not in response.text
    timeline = client.get("/v1/tasks/task-usage-limited/timeline").json()["events"]
    missing = next(
        event for event in timeline if event["event_type"] == "chat.response_missing"
    )
    assert missing["payload"]["error_category"] == "codex_usage_limit_exceeded"


def test_flow_followup_continues_same_task_without_risk_gate(api_runtime) -> None:
    client, _, _, _, orchestrator = api_runtime
    assert _chat(client).status_code == 200

    response = _chat(
        client,
        message="Open the browser and research bicycle balance online.",
        correlation_id="browser-correlation",
        idempotency_key="browser-once",
    )

    assert response.status_code == 200
    after = client.get("/v1/tasks/task-chat/timeline").json()["events"]
    assert any(
        event["event_type"] == "chat.user_message"
        and event["payload"].get("request_id") == "browser-once"
        for event in after
    )
    assert orchestrator.execute_count == 2


def test_create_and_resume_are_idempotent(api_runtime, tmp_path: Path) -> None:
    client, _, _, _, orchestrator = api_runtime
    first = _create(client)
    repeated = _create(client)
    assert repeated.json()["task_id"] == first.json()["task_id"]

    task_id = first.json()["task_id"]
    resume_headers = {
        "X-Correlation-ID": "turn-correlation",
        "Idempotency-Key": "resume-once",
    }
    body = {"cwd": str(tmp_path), "finalize_task": False}
    first_resume = client.post(
        f"/v1/tasks/{task_id}/resume",
        json=body,
        headers=resume_headers,
    )
    second_resume = client.post(
        f"/v1/tasks/{task_id}/resume",
        json=body,
        headers=resume_headers,
    )
    assert first_resume.status_code == 200
    assert second_resume.json()["idempotent_replay"] is True
    assert orchestrator.execute_count == 1


def test_pause_and_cancel_emit_canonical_state_events(api_runtime) -> None:
    client, _, service, _, _ = api_runtime
    task_id = _create(client).json()["task_id"]
    running = service.transition(
        task_id,
        TaskStatus.RUNNING,
        component="test",
        cause="test_start",
        idempotency_key="test-running",
    )
    assert running.status is TaskStatus.RUNNING

    pause = client.post(
        f"/v1/tasks/{task_id}/pause",
        headers={
            "X-Correlation-ID": "pause-correlation",
            "Idempotency-Key": "pause-once",
        },
    )
    cancel = client.post(
        f"/v1/tasks/{task_id}/cancel",
        headers={
            "X-Correlation-ID": "cancel-correlation",
            "Idempotency-Key": "cancel-once",
        },
    )
    assert pause.json()["status"] == "paused"
    assert cancel.json()["status"] == "canceled"
    transitions = [
        (event.status_from, event.status_to)
        for event in service.timeline(task_id)
        if event.event_type == "task.state_changed"
    ]
    assert (TaskStatus.RUNNING, TaskStatus.PAUSED) in transitions
    assert (TaskStatus.PAUSED, TaskStatus.CANCELED) in transitions


def test_approval_queue_api_is_not_mounted(api_runtime) -> None:
    client, *_ = api_runtime
    assert client.get("/v1/approvals/pending").status_code == 404
    assert client.post("/v1/approvals/legacy/approve").status_code == 404


def test_health_is_credential_safe_and_redacts_thread_by_default(api_runtime) -> None:
    client, _, service, _, _ = api_runtime
    task = service.create(
        session_id="health-session",
        correlation_id="health-correlation",
        description="health",
        component="test",
        cause="test",
        idempotency_key="health-create",
    )
    service.transition(
        task.task_id,
        TaskStatus.RUNNING,
        component="test",
        cause="test",
        idempotency_key="health-running",
        active_thread_id="thread-secret-value",
    )
    response = client.get("/v1/codex/health")
    body = response.json()
    serialized = response.text
    assert body["chatgpt_authenticated"] is True
    assert body["persistent_threads"] is True
    assert body["cli_fallback_enabled"] is False
    assert body["active_task"]["task_id"] == task.task_id
    assert body["active_task"]["active_thread_id"] == "…et-value"
    assert body["turn_model_evidence"]["resolved"] == {
        "model": "unknown",
        "effort": "unknown",
    }
    assert body["turn_model_evidence"]["confirmed"] == {
        "model": False,
        "effort": False,
    }
    assert "super-secret" not in serialized
    assert "[REDACTED]" in serialized


def test_task_summary_exposes_confirmed_turn_model_evidence(api_runtime) -> None:
    client, store, _, _, _ = api_runtime
    task = _create(client).json()
    timestamp = "2026-08-01T00:00:00+00:00"
    store.save_thread(
        CodexThreadRecord(
            task_id=task["task_id"],
            session_id=task["session_id"],
            correlation_id="model-thread-correlation",
            thread_id="thread-confirmed-value",
            backend=CodexBackendKind.PYTHON_SDK,
            sandbox=SandboxMode.READ_ONLY,
            approval_mode=ApprovalMode.DENY_ALL,
            cwd="C:\\isolated",
            model_config={},
            status="idle",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    store.save_turn(
        CodexTurnRecord(
            turn_id="turn-confirmed-value",
            task_id=task["task_id"],
            session_id=task["session_id"],
            correlation_id="model-turn-correlation",
            thread_id="thread-confirmed-value",
            backend=CodexBackendKind.PYTHON_SDK,
            sandbox=SandboxMode.READ_ONLY,
            approval_mode=ApprovalMode.DENY_ALL,
            cwd="C:\\isolated",
            status="completed",
            created_at=timestamp,
            updated_at=timestamp,
            runtime_evidence={
                "requested_model": None,
                "requested_effort": None,
                "actual_model": "gpt-confirmed",
                "actual_effort": "xhigh",
                "evidence_source": "python_sdk_app_server_thread_start",
                "sdk_version": "0.144.4",
                "runtime_version": "0.144.4",
            },
        )
    )

    summary = client.get(f"/v1/tasks/{task['task_id']}/summary").json()
    evidence = summary["turn_model_evidence"]

    assert evidence["resolved"] == {
        "model": "gpt-confirmed",
        "effort": "xhigh",
    }
    assert evidence["confirmed"] == {"model": True, "effort": True}
    assert evidence["backend"] == "python_sdk"
    assert evidence["sdk_version"] == "0.144.4"
    assert evidence["runtime_version"] == "0.144.4"
    assert evidence["thread_id"] == "…ed-value"
    assert evidence["turn_id"] is None


def test_usage_endpoint_keeps_turn_and_thread_values_separate(api_runtime) -> None:
    client, store, service, _, _ = api_runtime
    task_id = _create(client).json()["task_id"]
    store.save_usage(
        task_id=task_id,
        turn_id="turn",
        turn_input_tokens=40,
        turn_output_tokens=10,
        thread_input_tokens=140,
        thread_output_tokens=20,
        warning=False,
        hard_exceeded=False,
        reason=None,
        source_event_id="usage-event",
    )
    response = client.get(f"/v1/tasks/{task_id}/usage")
    assert response.status_code == 200
    body = response.json()
    assert body["turns"][0]["input_tokens"] == 40
    assert body["turns"][0]["output_tokens"] == 10
    assert body["turns"][0]["turn_id"] is None
    assert body["cumulative_thread"]["input_tokens"] == 140
    assert body["cumulative_thread"]["output_tokens"] == 20
    assert body["task_total_tokens"] == 50


def test_owned_task_runtime_and_trace_store_close_on_server_shutdown() -> None:
    class Closable:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class ClosableOrchestrator:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    engine = MagicMock()
    engine.engine_id = "fake"
    engine.health.return_value = True
    engine.list_models.return_value = ["fake"]
    store = Closable()
    traces = Closable()
    orchestrator = ClosableOrchestrator()
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    app = create_app(
        engine,
        "fake",
        bus=EventBus(),
        config=config,
        trace_store=traces,
        task_store=store,
        codex_orchestrator=orchestrator,
        owns_task_runtime=True,
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert orchestrator.closed is True
    assert store.closed is True
    assert traces.closed is True


def test_lifespan_shutdown_is_idempotent_after_partial_cleanup_failure() -> None:
    class FlakyMemory:
        def __init__(self) -> None:
            self.calls = 0

        def stop(self) -> None:
            self.calls += 1
            raise RuntimeError("synthetic cleanup failure")

    class ClosableVault:
        def __init__(self) -> None:
            self.calls = 0

        def close(self) -> None:
            self.calls += 1

    engine = MagicMock()
    engine.engine_id = "fake"
    engine.health.return_value = True
    engine.list_models.return_value = ["fake"]
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    memory = FlakyMemory()
    vault = ClosableVault()
    app = create_app(
        engine,
        "fake",
        bus=EventBus(),
        config=config,
        memory_service=memory,
        vault_memory_service=vault,
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert memory.calls == 1
    assert vault.calls == 1
    assert app.state.shutdown_complete is True
