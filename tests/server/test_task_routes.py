"""Integration tests for the local canonical task and approval API."""

from __future__ import annotations

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
    CodexBackendKind,
    CodexHealth,
    SandboxMode,
)
from openjarvis.core.config import JarvisConfig  # noqa: E402
from openjarvis.core.events import EventBus  # noqa: E402
from openjarvis.server.app import create_app  # noqa: E402
from openjarvis.server.approval_routes import router as approval_router  # noqa: E402
from openjarvis.server.task_routes import (  # noqa: E402
    _parse_tool_proposal,
    router as task_router,
)
from openjarvis.tasks.approval import PersistentApprovalBroker  # noqa: E402
from openjarvis.tasks.orchestrator import TaskExecutionResult  # noqa: E402
from openjarvis.tasks.service import TaskService  # noqa: E402
from openjarvis.tasks.store import TaskStore  # noqa: E402
from openjarvis.tasks.types import (  # noqa: E402
    ApprovalKind,
    TaskOutcome,
    TaskStatus,
)
from openjarvis.tools.approval_store import ApprovalStore  # noqa: E402

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
    import openjarvis.server.approval_routes as approval_routes

    store = TaskStore(tmp_path / "tasks.db")
    service = TaskService(store)
    broker = PersistentApprovalBroker(store, service, timeout_seconds=1)
    orchestrator = FakeOrchestrator(service)
    legacy_store = ApprovalStore(db_path=str(tmp_path / "legacy-approvals.db"))
    original_legacy = approval_routes._store
    approval_routes._store = legacy_store

    app = FastAPI()
    app.state.task_store = store
    app.state.task_service = service
    app.state.approval_broker = broker
    app.state.codex_orchestrator = orchestrator
    assistant_workspace = tmp_path / "assistant-workspace"
    assistant_workspace.mkdir()
    app.state.assistant_workspace = assistant_workspace
    app.state.config = SimpleNamespace(
        codex=SimpleNamespace(
            analysis_sandbox="read_only",
            approval_mode="deny_all",
            allow_cli_fallback=False,
        )
    )
    app.include_router(task_router)
    app.include_router(approval_router)
    try:
        yield TestClient(app), store, service, broker, orchestrator
    finally:
        approval_routes._store = original_legacy
        legacy_store.close()
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
    voice = [
        event for event in timeline if event["event_type"] == "chat.user_message"
    ][-1]
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
    assert task["risk_level"] == 1
    kwargs = orchestrator.last_execute_kwargs
    assert kwargs["cwd"] == kwargs["isolated_workspace"]
    assert kwargs["cwd"].name == "assistant-workspace"
    assert "do not commit or push" in kwargs["developer_instructions"].lower()
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
        "risk_level": 1,
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
    timeline = client.get(
        "/v1/tasks/task-browser-explanation/timeline"
    ).json()["events"]
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
        '</openjarvis_tool_proposal>'
    ) == ("desktop.windows", {})
    assert _parse_tool_proposal(
        'I will do it. <openjarvis_tool_proposal>{"tool_id":"desktop.windows",'
        '"arguments":{}}</openjarvis_tool_proposal>'
    ) is None
    assert _parse_tool_proposal(
        '<openjarvis_tool_proposal>{"tool_id":"desktop.windows",'
        '"arguments":{},"risk_level":0}</openjarvis_tool_proposal>'
    ) is None


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


def test_higher_risk_followup_requires_new_task_before_user_event(api_runtime) -> None:
    client, _, _, _, orchestrator = api_runtime
    assert _chat(client).status_code == 200
    before = client.get("/v1/tasks/task-chat/timeline").json()["events"]

    response = _chat(
        client,
        message="Open the browser and research bicycle balance online.",
        correlation_id="browser-correlation",
        idempotency_key="browser-once",
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith("NEW_TASK_REQUIRED:")
    after = client.get("/v1/tasks/task-chat/timeline").json()["events"]
    assert after == before
    assert orchestrator.execute_count == 1


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


def test_phase3_approval_is_visible_and_decided_once(
    api_runtime,
    tmp_path: Path,
) -> None:
    client, store, service, _, _ = api_runtime
    task = service.create(
        task_id="approval-task",
        session_id="approval-session",
        correlation_id="approval-correlation",
        description="write in test workspace",
        risk_level=1,
        component="test",
        cause="test",
        idempotency_key="approval-task-create",
    )
    service.transition(
        task.task_id,
        TaskStatus.RUNNING,
        component="test",
        cause="test",
        idempotency_key="approval-task-running",
    )
    store.save_thread(
        CodexThreadRecord(
            task_id=task.task_id,
            session_id=task.session_id,
            correlation_id="approval-thread-correlation",
            thread_id="approval-thread",
            backend=CodexBackendKind.APP_SERVER,
            sandbox=SandboxMode.WORKSPACE_WRITE,
            approval_mode=ApprovalMode.BROKERED,
            cwd=str(tmp_path),
            model_config={},
            status="active",
            created_at="2026-07-30T00:00:00+00:00",
            updated_at="2026-07-30T00:00:00+00:00",
        )
    )
    approval = store.queue_approval(
        request_id="approval-request",
        task_id=task.task_id,
        thread_id="approval-thread",
        turn_id=None,
        item_id="item",
        action_id="action",
        kind=ApprovalKind.FILE_CHANGE,
        action="write report",
        target=str(tmp_path / "report.md"),
        effect="Write one report in the isolated workspace.",
        risk_level=1,
        sandbox="workspace_write",
        cwd=str(tmp_path),
        undo="restore from diff",
    )

    pending = client.get("/v1/approvals/pending").json()["actions"]
    phase3 = next(item for item in pending if item["id"] == approval.approval_id)
    assert phase3["target"].endswith("report.md")
    assert phase3["risk_level"] == 1
    assert phase3["sandbox"] == "workspace_write"

    headers = {
        "X-Correlation-ID": "decision-correlation",
        "Idempotency-Key": "decision-once",
    }
    first = client.post(
        f"/v1/approvals/{approval.approval_id}/approve",
        headers=headers,
    )
    repeated = client.post(
        f"/v1/approvals/{approval.approval_id}/approve",
        headers=headers,
    )
    assert first.json()["status"] == "approved"
    assert repeated.json()["status"] == "approved"
    decisions = [
        event
        for event in service.timeline(task.task_id)
        if event.event_type == "approval.user_decided"
    ]
    assert len(decisions) == 1


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
