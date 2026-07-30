"""Tests for the unified, credential-safe system health API."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.system_health_routes import router


class FakeCodex:
    async def health(self):
        return (
            SimpleNamespace(
                backend=SimpleNamespace(value="python_sdk"),
                available=True,
                authenticated=True,
                auth_mode="chatgpt",
                runtime_version="test",
                degraded_backend=False,
                detail="secret-token-must-not-appear",
            ),
        )


def test_system_health_is_unified_and_credential_safe() -> None:
    app = FastAPI()
    app.state.codex_orchestrator = FakeCodex()
    app.state.task_service = None
    app.state.task_store = None
    app.state.trace_store = None
    app.state.tool_action_service = None
    app.state.browser_session_service = None
    app.state.vault_memory_service = None
    app.state.speech_backend = None
    app.state.tts_backend = None
    app.state.api_key = "server-secret"
    app.include_router(router)

    response = TestClient(app).get("/v1/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["credential_safe"] is True
    assert body["open_tasks"] == 0
    assert body["last_error_category"] is None
    assert body["components"]["codex"]["authenticated"] is True
    assert set(body["components"]) == {
        "server",
        "codex",
        "memory",
        "task_store",
        "trace_store",
        "tools",
        "browser",
        "desktop_adapter",
        "speech",
    }
    serialized = response.text
    assert "server-secret" not in serialized
    assert "secret-token-must-not-appear" not in serialized
