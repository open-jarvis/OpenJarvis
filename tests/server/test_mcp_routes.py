"""Loopback management tests for persistent MCP server configuration."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.mcp.registry import MCPServerRegistry
from openjarvis.server.mcp_routes import router


def _client(tmp_path) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.mcp_server_registry = MCPServerRegistry(tmp_path / "mcp-servers.json")
    action_service = MagicMock()
    action_service.catalog.list.return_value = ()
    app.state.tool_action_service = action_service
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {
        "X-Correlation-ID": "test-correlation",
        "Idempotency-Key": "test-idempotency",
    }


def _payload() -> dict:
    return {
        "server_id": "weather",
        "label": "Weather",
        "transport": "http",
        "enabled": True,
        "url": "http://127.0.0.1:8765/mcp",
        "command": "",
        "args": [],
        "token_env": "MCP_WEATHER_API_KEY",
        "include_tools": [],
        "exclude_tools": [],
        "tool_policies": {},
    }


def test_put_and_list_never_return_token_values(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.put(
        "/v1/mcp/servers/weather", json=_payload(), headers=_headers()
    )
    assert response.status_code == 200

    status = client.get("/v1/mcp/status")
    assert status.status_code == 200
    server = status.json()["servers"][0]
    assert server["server_id"] == "weather"
    assert server["token_env"] == "MCP_WEATHER_API_KEY"
    assert "token" not in server


def test_mutations_require_correlation_and_idempotency_headers(tmp_path) -> None:
    response = _client(tmp_path).put("/v1/mcp/servers/weather", json=_payload())
    assert response.status_code == 422


def test_path_and_payload_ids_must_match(tmp_path) -> None:
    response = _client(tmp_path).put(
        "/v1/mcp/servers/other", json=_payload(), headers=_headers()
    )
    assert response.status_code == 409


def test_registry_rejects_credentials_in_url(tmp_path) -> None:
    payload = _payload()
    payload["url"] = "https://user:secret@example.test/mcp"
    response = _client(tmp_path).put(
        "/v1/mcp/servers/weather", json=payload, headers=_headers()
    )
    assert response.status_code == 422


def test_delete_removes_persistent_server(tmp_path) -> None:
    client = _client(tmp_path)
    assert (
        client.put(
            "/v1/mcp/servers/weather", json=_payload(), headers=_headers()
        ).status_code
        == 200
    )
    response = client.delete("/v1/mcp/servers/weather", headers=_headers())
    assert response.status_code == 200
    assert client.get("/v1/mcp/status").json()["servers"] == []
