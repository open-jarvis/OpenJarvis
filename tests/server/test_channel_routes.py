"""Tests for /v1/channels endpoints.

Requires the ``[server]`` optional extra (fastapi, uvicorn, pydantic).
Skipped automatically when those packages are not installed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi", reason="openjarvis[server] not installed")

from openjarvis.channels._stubs import ChannelStatus  # noqa: E402


@pytest.fixture
def mock_engine():
    """Minimal mock engine for app creation."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": "Hello!",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


@pytest.fixture
def mock_bridge():
    """Mock channel bridge."""
    bridge = MagicMock()
    bridge.status.return_value = ChannelStatus.CONNECTED
    bridge.list_channels.return_value = ["slack", "discord", "telegram"]
    bridge.send.return_value = True
    return bridge


@pytest.fixture
def app_with_bridge(mock_engine, mock_bridge):
    """FastAPI app with channel bridge configured."""
    from openjarvis.server.app import create_app

    return create_app(
        mock_engine,
        "test-model",
        channel_bridge=mock_bridge,
    )


@pytest.fixture
def app_without_bridge(mock_engine):
    """FastAPI app without channel bridge."""
    from openjarvis.server.app import create_app

    return create_app(mock_engine, "test-model")


@pytest.fixture
def client_with_bridge(app_with_bridge):
    """Test client with channel bridge."""
    from starlette.testclient import TestClient

    return TestClient(app_with_bridge)


@pytest.fixture
def client_without_bridge(app_without_bridge):
    """Test client without channel bridge."""
    from starlette.testclient import TestClient

    return TestClient(app_without_bridge)


class TestListChannels:
    def test_list_channels_with_bridge(self, client_with_bridge, mock_bridge):
        resp = client_with_bridge.get("/v1/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert data["channels"] == ["slack", "discord", "telegram"]
        assert data["status"] == "connected"

    def test_list_channels_no_bridge(self, client_without_bridge):
        resp = client_without_bridge.get("/v1/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert data["channels"] == []
        assert "not configured" in data.get("message", "").lower()


class TestChannelSend:
    def test_send_success(self, client_with_bridge, mock_bridge):
        resp = client_with_bridge.post(
            "/v1/channels/send",
            json={"channel": "slack", "content": "Hello from Jarvis"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "sent"
        assert data["channel"] == "slack"
        mock_bridge.send.assert_called_once()

    def test_send_no_bridge(self, client_without_bridge):
        resp = client_without_bridge.post(
            "/v1/channels/send",
            json={"channel": "slack", "content": "Hello"},
        )
        assert resp.status_code == 503

    def test_send_missing_channel(self, client_with_bridge):
        resp = client_with_bridge.post(
            "/v1/channels/send",
            json={"content": "Hello"},
        )
        assert resp.status_code == 400

    def test_send_missing_content(self, client_with_bridge):
        resp = client_with_bridge.post(
            "/v1/channels/send",
            json={"channel": "slack"},
        )
        assert resp.status_code == 400

    def test_send_failure(self, client_with_bridge, mock_bridge):
        mock_bridge.send.return_value = False
        resp = client_with_bridge.post(
            "/v1/channels/send",
            json={"channel": "slack", "content": "Hello"},
        )
        assert resp.status_code == 502


class TestChannelStatus:
    def test_status_with_bridge(self, client_with_bridge):
        resp = client_with_bridge.get("/v1/channels/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connected"

    def test_status_no_bridge(self, client_without_bridge):
        resp = client_without_bridge.get("/v1/channels/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_configured"
