"""Integration tests for the local canonical task and approval API."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.codex.store import CodexThreadRecord  # noqa: E402
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
from openjarvis.server.task_routes import router as task_router  # noqa: E402
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
        del prompt, kwargs
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
    assert body["active_task"]["active_thread_id"] == "…et-value"
    assert "super-secret" not in serialized
    assert "[REDACTED]" in serialized


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
