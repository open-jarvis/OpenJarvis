from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.flow import FlowSessionAuthority
from openjarvis.server.app import create_app
from openjarvis.server.flow_routes import router

SECRET = "a" * 64


def _assertion() -> dict[str, object]:
    authenticated_at = int(time.time())
    nonce = "native-proof-nonce-1234"
    owner = "windows-owner"
    message = f"flow-v1\n{nonce}\n{authenticated_at}\n{owner}".encode()
    return {
        "nonce": nonce,
        "authenticated_at": authenticated_at,
        "signature": hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest(),
        "owner": owner,
    }


def test_browser_cannot_activate_flow_but_native_bridge_can() -> None:
    app = FastAPI()
    app.state.flow_authority = FlowSessionAuthority(SECRET)
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/v1/flow/status").json()["mode"] == "locked"
        assert client.post("/v1/flow/activate", json=_assertion()).status_code == 403

        response = client.post(
            "/v1/flow/activate",
            json=_assertion(),
            headers={"X-OpenJarvis-Native-Bridge": "tauri"},
        )
        assert response.status_code == 200
        assert response.json()["mode"] == "flow"
        assert response.json()["capabilities"]["desktop"] == "full"

        assert client.post("/v1/flow/lock").json()["mode"] == "locked"


def test_approval_queue_is_not_mounted_in_the_application() -> None:
    app = FastAPI()
    app.state.flow_authority = FlowSessionAuthority()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/v1/approvals/pending").status_code == 404


def test_full_application_does_not_mount_legacy_approval_workflows() -> None:
    engine = MagicMock()
    engine.engine_id = "flow-test"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    app = create_app(
        engine,
        "test-model",
        flow_authority=FlowSessionAuthority(SECRET),
    )

    paths = app.openapi()["paths"]
    assert "/v1/approvals/pending" not in paths
    assert "/v1/website-staging/demo" not in paths
    assert "/v1/learning/health" not in paths


def test_flow_activity_rejects_a_different_session() -> None:
    app = FastAPI()
    authority = FlowSessionAuthority(SECRET)
    app.state.flow_authority = authority
    app.include_router(router)

    with TestClient(app) as client:
        status = client.post(
            "/v1/flow/activate",
            json=_assertion(),
            headers={"X-OpenJarvis-Native-Bridge": "tauri"},
        ).json()
        assert status["session_id"]
        response = client.post(
            "/v1/flow/activity",
            json={"session_id": "not-the-active-session"},
        )
        assert response.status_code == 403
        assert authority.status().mode.value == "flow"


def test_model_text_cannot_create_a_flow_grant() -> None:
    app = FastAPI()
    app.state.flow_authority = FlowSessionAuthority(SECRET)
    app.include_router(router)
    assertion = _assertion()
    assertion["signature"] = "0" * 64

    with TestClient(app) as client:
        response = client.post(
            "/v1/flow/activate",
            json=assertion,
            headers={"X-OpenJarvis-Native-Bridge": "tauri"},
        )
        assert response.status_code == 403
        assert client.get("/v1/flow/status").json()["mode"] == "locked"
