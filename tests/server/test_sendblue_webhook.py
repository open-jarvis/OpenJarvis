"""Integration tests for the SendBlue webhook endpoint.

Tests the /webhooks/sendblue route, health check endpoint, and the
full flow from incoming webhook -> bridge -> agent -> send response.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from openjarvis.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_sendblue():
    if not ChannelRegistry.contains("sendblue"):
        from openjarvis.channels.sendblue import SendBlueChannel

        ChannelRegistry.register_value("sendblue", SendBlueChannel)


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.handle_incoming.return_value = "Here are your results..."
    return bridge


@pytest.fixture
def sendblue_channel():
    from openjarvis.channels.sendblue import SendBlueChannel

    ch = SendBlueChannel(
        api_key_id="test_key",
        api_secret_key="test_secret",
        from_number="+15551234567",
    )
    ch.connect()
    return ch


@pytest.fixture
def webhook_app(mock_bridge, sendblue_channel):
    from openjarvis.server.webhook_routes import create_webhook_router

    app = FastAPI()
    router = create_webhook_router(
        bridge=mock_bridge,
        sendblue_channel=sendblue_channel,
    )
    app.include_router(router)
    return app


@pytest.fixture
def client(webhook_app):
    return TestClient(webhook_app)


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


class TestSendBlueWebhook:
    def test_incoming_message_returns_200(self, client):
        resp = client.post(
            "/webhooks/sendblue",
            json={
                "from_number": "+19127130720",
                "to_number": "+15551234567",
                "content": "Hello Jarvis",
                "message_handle": "msg-001",
                "is_outbound": False,
                "status": "RECEIVED",
                "service": "iMessage",
            },
        )
        assert resp.status_code == 200

    def test_outbound_status_callback_ignored(self, client, mock_bridge):
        resp = client.post(
            "/webhooks/sendblue",
            json={
                "from_number": "+15551234567",
                "content": "Sent message",
                "is_outbound": True,
            },
        )
        assert resp.status_code == 200
        mock_bridge.handle_incoming.assert_not_called()

    def test_empty_content_ignored(self, client, mock_bridge):
        resp = client.post(
            "/webhooks/sendblue",
            json={
                "from_number": "+19127130720",
                "content": "",
                "is_outbound": False,
            },
        )
        assert resp.status_code == 200
        mock_bridge.handle_incoming.assert_not_called()

    def test_missing_from_number_ignored(self, client, mock_bridge):
        resp = client.post(
            "/webhooks/sendblue",
            json={
                "content": "Hello",
                "is_outbound": False,
            },
        )
        assert resp.status_code == 200
        mock_bridge.handle_incoming.assert_not_called()

    def test_webhook_secret_validation(self, mock_bridge):
        """When a webhook secret is set, reject requests without it."""
        from openjarvis.channels.sendblue import SendBlueChannel
        from openjarvis.server.webhook_routes import create_webhook_router

        ch = SendBlueChannel(
            api_key_id="k",
            api_secret_key="s",
            from_number="+1555",
            webhook_secret="mysecret",
        )
        ch.connect()

        app = FastAPI()
        router = create_webhook_router(
            bridge=mock_bridge, sendblue_channel=ch
        )
        app.include_router(router)
        c = TestClient(app)

        # Without secret header -> rejected
        resp = c.post(
            "/webhooks/sendblue",
            json={
                "from_number": "+19127130720",
                "content": "Hello",
                "is_outbound": False,
            },
        )
        assert resp.status_code == 403

        # With correct secret -> accepted
        resp = c.post(
            "/webhooks/sendblue",
            json={
                "from_number": "+19127130720",
                "content": "Hello",
                "is_outbound": False,
                "message_handle": "msg-002",
            },
            headers={"x-sendblue-secret": "mysecret"},
        )
        assert resp.status_code == 200

    def test_no_bridge_returns_200(self, sendblue_channel):
        """When no bridge exists, webhook should not crash."""
        from openjarvis.server.webhook_routes import create_webhook_router

        app = FastAPI()
        router = create_webhook_router(
            bridge=None, sendblue_channel=sendblue_channel
        )
        app.include_router(router)
        c = TestClient(app)

        resp = c.post(
            "/webhooks/sendblue",
            json={
                "from_number": "+19127130720",
                "content": "Hello",
                "is_outbound": False,
            },
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Health endpoint (requires agent_manager_routes)
# ---------------------------------------------------------------------------


class TestSendBlueHealth:
    @pytest.fixture
    def health_app(self, sendblue_channel):
        app = FastAPI()
        app.state.sendblue_channel = sendblue_channel
        app.state.channel_bridge = MagicMock()
        app.state.channel_bridge._channels = {"sendblue": sendblue_channel}

        from openjarvis.server.agent_manager_routes import (
            create_agent_manager_router,
        )

        mgr = MagicMock()
        mgr.list_agents.return_value = []
        routers = create_agent_manager_router(mgr)
        sendblue_router = routers[4]  # 5th element is sendblue_router
        app.include_router(sendblue_router)
        return app

    def test_health_ready(self, health_app):
        c = TestClient(health_app)
        resp = c.get("/v1/channels/sendblue/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel_connected"] is True
        assert data["bridge_wired"] is True
        assert data["ready"] is True

    def test_health_not_ready(self):
        app = FastAPI()
        # No sendblue_channel or bridge on state

        from openjarvis.server.agent_manager_routes import (
            create_agent_manager_router,
        )

        mgr = MagicMock()
        mgr.list_agents.return_value = []
        routers = create_agent_manager_router(mgr)
        sendblue_router = routers[4]
        app.include_router(sendblue_router)

        c = TestClient(app)
        resp = c.get("/v1/channels/sendblue/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
