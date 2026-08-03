"""Local authenticated tool/action/browser API integration tests."""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.browser.models import (  # noqa: E402
    BrowserControlHealth,
    BrowserRecoveryRecord,
    BrowserSession,
    BrowserSessionStatus,
)
from openjarvis.flow import FlowSessionAuthority  # noqa: E402
from openjarvis.server.auth_middleware import AuthMiddleware  # noqa: E402
from openjarvis.server.tool_browser_routes import router  # noqa: E402
from openjarvis.tasks import ExecutionLane, TaskService, TaskStore  # noqa: E402
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext  # noqa: E402
from openjarvis.tools.action_service import (  # noqa: E402
    RegisteredToolRuntime,
    ToolActionService,
)
from openjarvis.tools.action_store import ActionStore  # noqa: E402
from openjarvis.tools.actions import (  # noqa: E402
    ParameterSource,
    ToolProposal,
    VerificationResult,
)
from openjarvis.tools.manifest import (  # noqa: E402
    IdempotencyPolicy,
    NetworkPolicy,
    SecretPolicy,
    SideEffectClass,
    ToolManifest,
    ToolManifestCatalog,
)

_AUTH = {"Authorization": "Bearer oj_sk_phase5"}


def _manifest(tool_id: str, risk: RiskLevel) -> ToolManifest:
    interactive = risk >= RiskLevel.EXTERNAL_PREPARATION
    return ToolManifest(
        tool_id=tool_id,
        name=tool_id,
        description="Synthetic API tool.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        output_schema={"type": "object"},
        capability="test:api",
        risk_level=risk,
        allowed_lanes=(
            ExecutionLane.INTERACTIVE if interactive else ExecutionLane.MODEL,
        ),
        supported_platforms=("windows", "linux", "darwin"),
        timeout=2,
        max_retries=0,
        idempotency_policy=IdempotencyPolicy.KEY_REQUIRED,
        side_effect_class=(
            SideEffectClass.EXTERNAL_WRITE
            if risk >= RiskLevel.DESTRUCTIVE_OR_SENSITIVE
            else SideEffectClass.LOCAL_READ
        ),
        verification_strategy="exact synthetic comparison",
        undo_strategy="synthetic reset",
        required_approval=risk >= RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
        network_policy=NetworkPolicy.DENY,
        secret_policy=SecretPolicy.REDACT,
        log_redaction_policy="credentials",
    )


def _proposal(
    manifest: ToolManifest,
    *,
    idempotency_key: str,
) -> ToolProposal:
    return ToolProposal(
        task_id="task-api",
        session_id="session-api",
        correlation_id="correlation-api",
        thread_id="thread-api",
        turn_id="turn-api",
        item_id=f"item-{idempotency_key}",
        tool_id=manifest.tool_id,
        arguments={"value": "synthetic"},
        expected_result="synthetic value observed",
        expected_side_effect=manifest.side_effect_class,
        risk_level=manifest.risk_level,
        capability=manifest.capability,
        target="synthetic target",
        verification_plan="exact comparison",
        undo_plan="synthetic reset",
        idempotency_key=idempotency_key,
        timeout_seconds=1,
        rationale="API contract test",
        parameter_sources={"value": ParameterSource.USER},
    )


class FakeBrowserService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sessions: dict[str, BrowserSession] = {}

    def create(self):
        profile = self.root / "owned-temp-profile"
        profile.mkdir(exist_ok=True)
        session = BrowserSession(profile_path=profile, control_port=9133)
        session.status = BrowserSessionStatus.READY
        session.browser_pid = 1234
        session.control_service_pid = 1234
        session.owned_process = True
        self.sessions[session.session_id] = session
        return session

    def list(self):
        return tuple(self.sessions.values())

    def health(self, session_id):
        session = self.sessions[session_id]
        return BrowserControlHealth(
            session_id=session.session_id,
            browser_process_present=True,
            browser_pid=1234,
            browser_start_time="synthetic",
            profile_path=str(session.profile_path),
            control_service_present=True,
            control_service_pid=1234,
            control_port=session.control_port,
            port_open=True,
            port_owner_pid=1234,
            port_owner_matches=True,
            health_endpoint="http://127.0.0.1:9133/json/version",
            connection_ok=True,
            last_successful_heartbeat="synthetic",
            cause="healthy",
        )

    def health_all(self):
        return tuple(self.health(session_id) for session_id in self.sessions)

    def recover(self, session_id):
        session = self.sessions[session_id]
        session.recovery_attempts += 1
        return BrowserRecoveryRecord(
            session_id=session_id,
            attempt=1,
            maximum_attempts=1,
            cause="synthetic_disconnect",
            reconnect_attempted=True,
            reconnect_succeeded=True,
            control_restart_attempted=False,
            control_restart_succeeded=False,
            result="reconnected",
            checkpoint="browser.ready",
            started_at="synthetic",
            completed_at="synthetic",
        )

    def close(self, session_id):
        session = self.sessions[session_id]
        session.status = BrowserSessionStatus.CLOSED
        session.browser_pid = None
        session.control_service_pid = None
        return session


@pytest.fixture
def api(tmp_path: Path):
    read = _manifest("test.api.read", RiskLevel.READ_ONLY)
    sensitive = _manifest(
        "test.api.sensitive",
        RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
    )
    manifests = {item.tool_id: item for item in (read, sensitive)}
    task_store = TaskStore(tmp_path / "tasks.db")
    tasks = TaskService(task_store)
    tasks.create(
        task_id="task-api",
        session_id="session-api",
        correlation_id="correlation-api",
        description="synthetic API task",
        component="test",
        cause="test",
        idempotency_key="create-api-task",
    )
    action_store = ActionStore(tmp_path / "actions.db")
    secret = "f" * 64
    authenticated_at = int(time.time())
    nonce = "tool-browser-native-proof"
    owner = "test-owner"
    message = f"flow-v1\n{nonce}\n{authenticated_at}\n{owner}".encode()
    authority = FlowSessionAuthority(secret)
    authority.activate_flow(
        nonce=nonce,
        authenticated_at=authenticated_at,
        signature=hmac.new(secret.encode(), message, hashlib.sha256).hexdigest(),
        owner=owner,
    )

    def context(proposal):
        manifest = manifests[proposal.tool_id]
        return ToolPolicyContext(
            granted_capabilities=frozenset({"test:api"}),
            execution_lane=manifest.allowed_lanes[0],
            requested_risk=manifest.risk_level,
            proposal_capability="test:api",
            allowed_roots=(tmp_path,),
        )

    def verify(proposal, output):
        return VerificationResult(
            passed=output["value"] == proposal.arguments["value"],
            observed_state=output["value"],
            expected_state=proposal.arguments["value"],
        )

    runtime = RegisteredToolRuntime(
        handler=lambda arguments: {"value": arguments["value"]},
        verifier=verify,
    )
    actions = ToolActionService(
        catalog=ToolManifestCatalog(tuple(manifests.values())),
        store=action_store,
        context_factory=context,
        runtimes={tool_id: runtime for tool_id in manifests},
        artifact_root=tmp_path / "artifacts",
        flow_authority=authority,
        task_service=tasks,
    )
    app = FastAPI()
    app.state.flow_authority = authority
    app.state.tool_action_service = actions
    app.state.browser_session_service = FakeBrowserService(tmp_path)
    app.add_middleware(AuthMiddleware, api_key="oj_sk_phase5")
    app.include_router(router)
    try:
        yield TestClient(app), read, sensitive
    finally:
        action_store.close()
        task_store.close()


def _headers(idempotency_key: str) -> dict[str, str]:
    return _AUTH | {
        "X-Correlation-ID": "correlation-api",
        "Idempotency-Key": idempotency_key,
    }


def test_read_endpoints_and_authentication(api) -> None:
    client, read, _ = api
    assert client.get("/v1/tools").status_code == 401
    listed = client.get("/v1/tools", headers=_AUTH)
    assert listed.status_code == 200
    assert listed.json()["count"] == 2
    assert client.get(f"/v1/tools/{read.tool_id}", headers=_AUTH).status_code == 200
    health = client.get("/v1/tools/health", headers=_AUTH).json()
    assert health["healthy"] is True
    assert health["lanes"]["interactive_lane"]["limit"] == 1


def test_action_creation_is_idempotent_and_schema_validated(api) -> None:
    client, read, _ = api
    proposal = _proposal(read, idempotency_key="read-once")
    body = {"proposal": proposal.model_dump(mode="json"), "execute": True}
    first = client.post(
        "/v1/tasks/task-api/actions",
        json=body,
        headers=_headers("read-once"),
    )
    repeated = client.post(
        "/v1/tasks/task-api/actions",
        json=body,
        headers=_headers("read-once"),
    )
    assert first.status_code == 201
    assert first.json()["status"] == "completed"
    assert repeated.json()["action_id"] == first.json()["action_id"]
    listed = client.get("/v1/tasks/task-api/actions", headers=_AUTH).json()
    assert listed["count"] == 1


def test_sensitive_action_executes_directly_in_flow(api) -> None:
    client, _, sensitive = api
    proposal = _proposal(sensitive, idempotency_key="sensitive-once")
    created = client.post(
        "/v1/tasks/task-api/actions",
        json={"proposal": proposal.model_dump(mode="json")},
        headers=_headers("sensitive-once"),
    )
    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    action_id = created.json()["action_id"]
    removed_approval_endpoint = client.post(
        f"/v1/actions/{action_id}/approve",
        headers=_headers("approval-once"),
    )
    assert removed_approval_endpoint.status_code == 404


def test_mutations_require_headers_and_matching_identity(api) -> None:
    client, read, _ = api
    proposal = _proposal(read, idempotency_key="missing-headers")
    body = {"proposal": proposal.model_dump(mode="json")}
    assert (
        client.post(
            "/v1/tasks/task-api/actions",
            json=body,
            headers=_AUTH,
        ).status_code
        == 422
    )
    wrong = _headers("missing-headers") | {"X-Correlation-ID": "wrong"}
    assert (
        client.post(
            "/v1/tasks/task-api/actions",
            json=body,
            headers=wrong,
        ).status_code
        == 409
    )


def test_owned_browser_session_health_recovery_and_close(api) -> None:
    client, _, _ = api
    created = client.post(
        "/v1/browser/sessions",
        json={},
        headers=_headers("browser-create"),
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    health = client.get("/v1/browser/health", headers=_AUTH).json()
    assert health["healthy"] is True
    recovered = client.post(
        f"/v1/browser/sessions/{session_id}/recover",
        headers=_headers("browser-recover"),
    )
    assert recovered.json()["attempt"] == 1
    closed = client.delete(
        f"/v1/browser/sessions/{session_id}",
        headers=_headers("browser-close"),
    )
    assert closed.json()["status"] == "closed"
