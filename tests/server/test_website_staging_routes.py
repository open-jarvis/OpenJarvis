"""Local authenticated API gates for isolated website staging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.auth_middleware import AuthMiddleware
from openjarvis.server.website_staging_routes import router
from openjarvis.tasks import ExecutionLane, TaskService, TaskStore
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext
from openjarvis.tools.action_service import ToolActionService
from openjarvis.tools.action_store import ActionStore
from openjarvis.tools.manifest import ToolManifestCatalog
from openjarvis.website import (
    WebsiteFileProposal,
    WebsiteOperation,
    WebsiteOverwritePolicy,
    WebsiteStagingRequest,
    WebsiteStagingService,
    WebsiteVerificationPolicy,
    WebsiteWorkspaceStore,
)
from openjarvis.website.models import WebsiteExpectedFileType


@dataclass
class ApiHarness:
    client: TestClient
    service: WebsiteStagingService
    task_store: TaskStore
    action_store: ActionStore
    request: WebsiteStagingRequest
    proposals: tuple[WebsiteFileProposal, ...]


@pytest.fixture
def api_harness(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    task_store = TaskStore(tmp_path / "tasks.db")
    task_service = TaskService(task_store)
    task_service.create(
        task_id="task-api",
        session_id="session-api",
        correlation_id="correlation-api",
        description="synthetic website API pilot",
        execution_lane=ExecutionLane.MODEL,
        risk_level=1,
        component="api_test",
        cause="synthetic_fixture",
        idempotency_key="task-api-create",
    )
    action_store = ActionStore(tmp_path / "actions.db")
    context = ToolPolicyContext(
        granted_capabilities=frozenset({"website:stage"}),
        execution_lane=ExecutionLane.MODEL,
        requested_risk=RiskLevel.REVERSIBLE_WORKSPACE,
        proposal_capability="website:stage",
        allowed_roots=(staging,),
    )
    action_service = ToolActionService(
        catalog=ToolManifestCatalog(()),
        store=action_store,
        context_factory=lambda _proposal: context,
        runtimes={},
        artifact_root=tmp_path / "artifacts",
        task_service=task_service,
    )
    workspaces = WebsiteWorkspaceStore(staging, protected_roots=())
    workspaces.provision("workspace-api")
    service = WebsiteStagingService(
        workspace_store=workspaces,
        action_service=action_service,
        task_service=task_service,
    )
    proposals = (
        WebsiteFileProposal.from_text(
            relative_path="index.html",
            media_type="text/html",
            content='<html><head><link href="style.css" rel="stylesheet"></head>'
            "<body>API fixture</body></html>",
        ),
        WebsiteFileProposal.from_text(
            relative_path="style.css",
            media_type="text/css",
            content="body { color: #222; }",
        ),
    )
    request = WebsiteStagingRequest.create(
        request_id="request-api",
        task_id="task-api",
        session_id="session-api",
        correlation_id="correlation-api",
        workspace_id="workspace-api",
        operation=WebsiteOperation.CREATE_STATIC_SITE,
        allowed_source_files=(),
        requested_output_files=("index.html", "style.css"),
        expected_file_types=(
            WebsiteExpectedFileType(
                relative_path="index.html",
                media_type="text/html",
            ),
            WebsiteExpectedFileType(
                relative_path="style.css",
                media_type="text/css",
            ),
        ),
        maximum_files=4,
        maximum_total_bytes=4096,
        overwrite_policy=WebsiteOverwritePolicy.DENY,
        verification_policy=WebsiteVerificationPolicy.STRICT_STATIC,
        idempotency_key="idempotency-api",
        created_at=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
    )
    app = FastAPI()
    app.state.website_staging_service = service
    app.include_router(router)
    app.add_middleware(AuthMiddleware, api_key="local-api-key")
    client = TestClient(app)
    value = ApiHarness(
        client=client,
        service=service,
        task_store=task_store,
        action_store=action_store,
        request=request,
        proposals=proposals,
    )
    yield value
    client.close()
    action_store.close()
    task_store.close()


def headers(harness: ApiHarness, **changes: str) -> dict[str, str]:
    value = {
        "Authorization": "Bearer local-api-key",
        "X-Actor": "local-ui",
        "X-Correlation-ID": harness.request.correlation_id,
        "Idempotency-Key": harness.request.idempotency_key,
    }
    value.update(changes)
    return value


def preview(harness: ApiHarness):
    return harness.client.post(
        "/v1/website-staging/preview",
        headers=headers(harness),
        json={
            "request": harness.request.model_dump(mode="json"),
            "proposals": [item.model_dump(mode="json") for item in harness.proposals],
        },
    )


def test_api_requires_existing_authentication(api_harness: ApiHarness) -> None:
    response = api_harness.client.get("/v1/website-staging/workspace-api")
    assert response.status_code == 401


def test_preview_requires_actor_and_exact_headers(api_harness: ApiHarness) -> None:
    body = {
        "request": api_harness.request.model_dump(mode="json"),
        "proposals": [item.model_dump(mode="json") for item in api_harness.proposals],
    }
    missing_actor = headers(api_harness)
    missing_actor.pop("X-Actor")
    assert (
        api_harness.client.post(
            "/v1/website-staging/preview",
            headers=missing_actor,
            json=body,
        ).status_code
        == 422
    )
    mismatch = headers(api_harness, **{"X-Correlation-ID": "wrong"})
    assert (
        api_harness.client.post(
            "/v1/website-staging/preview",
            headers=mismatch,
            json=body,
        ).status_code
        == 409
    )


def test_preview_rejects_unknown_api_field(api_harness: ApiHarness) -> None:
    body = {
        "request": api_harness.request.model_dump(mode="json"),
        "proposals": [item.model_dump(mode="json") for item in api_harness.proposals],
        "publish": True,
    }
    response = api_harness.client.post(
        "/v1/website-staging/preview",
        headers=headers(api_harness),
        json=body,
    )
    assert response.status_code == 422


def test_preview_response_contains_no_content_or_absolute_path(
    api_harness: ApiHarness,
) -> None:
    response = preview(api_harness)
    assert response.status_code == 200
    payload = response.json()
    rendered = response.text
    assert payload["file_diffs"]
    assert "content_text" not in rendered
    assert "content_base64" not in rendered
    assert str(api_harness.service.workspaces.root) not in rendered


def test_apply_uses_request_approval_then_allow_once(api_harness: ApiHarness) -> None:
    plan = preview(api_harness).json()
    body = {
        "workspace_id": "workspace-api",
        "request_id": "request-api",
        "expected_preview_hash": plan["preview_hash"],
        "decision": "request_approval",
    }
    waiting = api_harness.client.post(
        "/v1/website-staging/apply",
        headers=headers(api_harness),
        json=body,
    )
    assert waiting.status_code == 200
    assert waiting.json()["action"]["status"] == "waiting_approval"
    assert waiting.json()["execution"] is None
    body["decision"] = "allow_once"
    completed = api_harness.client.post(
        "/v1/website-staging/apply",
        headers=headers(api_harness),
        json=body,
    )
    assert completed.status_code == 200
    assert completed.json()["action"]["status"] == "completed"
    assert completed.json()["execution"]["trace_evaluation_hash"]
    assert completed.json()["allow_once_only"] is True
    assert "always" not in completed.text.lower()


def test_validate_artifact_readback_and_rollback(api_harness: ApiHarness) -> None:
    plan = preview(api_harness).json()
    apply_response = api_harness.client.post(
        "/v1/website-staging/apply",
        headers=headers(api_harness),
        json={
            "workspace_id": "workspace-api",
            "request_id": "request-api",
            "expected_preview_hash": plan["preview_hash"],
            "decision": "allow_once",
        },
    )
    execution = apply_response.json()["execution"]
    validation = api_harness.client.post(
        "/v1/website-staging/validate",
        headers=headers(api_harness),
        json={
            "workspace_id": "workspace-api",
            "expected_manifest_hash": execution["after_manifest_sha256"],
        },
    )
    assert validation.status_code == 200
    assert validation.json()["passed"] is True
    artifacts = api_harness.client.get(
        "/v1/website-staging/workspace-api/artifacts",
        headers=headers(api_harness),
    )
    assert artifacts.status_code == 200
    assert len(artifacts.json()["artifacts"]) == 2
    rollback = api_harness.client.post(
        "/v1/website-staging/rollback",
        headers=headers(api_harness),
        json={
            "workspace_id": "workspace-api",
            "execution_id": execution["execution_id"],
            "expected_manifest_hash": execution["after_manifest_sha256"],
            "decision": "allow_once",
        },
    )
    assert rollback.status_code == 200
    assert rollback.json()["rollback"]["byte_identical"] is True


def test_api_fails_closed_without_service() -> None:
    app = FastAPI()
    app.state.website_staging_service = None
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/v1/website-staging/missing")
    assert response.status_code == 503
    client.close()


def test_api_rejects_non_loopback_client(api_harness: ApiHarness) -> None:
    remote = TestClient(
        api_harness.client.app,
        client=("198.51.100.10", 53000),
    )
    response = remote.get(
        "/v1/website-staging/workspace-api",
        headers=headers(api_harness),
    )
    assert response.status_code == 403
    remote.close()
