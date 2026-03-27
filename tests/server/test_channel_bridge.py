"""Tests for the ChannelBridge orchestrator."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi", reason="openjarvis[server] not installed")

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelStatus,
)
from openjarvis.core.events import EventBus
from openjarvis.server.channel_bridge import ChannelBridge
from openjarvis.server.session_store import SessionStore


class FakeChannel(BaseChannel):
    """Minimal channel for testing."""

    channel_id = "fake"

    def __init__(self) -> None:
        self._status = ChannelStatus.DISCONNECTED
        self._handlers: List[ChannelHandler] = []
        self.sent: List[Dict[str, Any]] = []

    def connect(self) -> None:
        self._status = ChannelStatus.CONNECTED

    def disconnect(self) -> None:
        self._status = ChannelStatus.DISCONNECTED

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        self.sent.append({"channel": channel, "content": content})
        return True

    def status(self) -> ChannelStatus:
        return self._status

    def list_channels(self) -> List[str]:
        return ["fake"]

    def on_message(self, handler: ChannelHandler) -> None:
        self._handlers.append(handler)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = SessionStore(db_path=str(Path(tmpdir) / "sessions.db"))
        yield s
        s.close()


@pytest.fixture
def bus():
    return EventBus(record_history=True)


@pytest.fixture
def mock_system():
    system = MagicMock()
    system.ask.return_value = {"content": "Hello from Jarvis!"}
    return system


@pytest.fixture
def bridge(store, bus, mock_system):
    fake = FakeChannel()
    fake.connect()
    b = ChannelBridge(
        channels={"fake": fake},
        session_store=store,
        bus=bus,
        system=mock_system,
    )
    return b


class TestBackwardCompatible:
    """ChannelBridge must work as a drop-in for the old bridge."""

    def test_list_channels(self, bridge):
        assert "fake" in bridge.list_channels()

    def test_status_connected(self, bridge):
        assert bridge.status() == ChannelStatus.CONNECTED

    def test_status_disconnected_when_none_connected(self, store, bus, mock_system):
        fake = FakeChannel()  # not connected
        b = ChannelBridge(
            channels={"fake": fake},
            session_store=store,
            bus=bus,
            system=mock_system,
        )
        assert b.status() == ChannelStatus.DISCONNECTED

    def test_send_routes_to_adapter(self, bridge):
        result = bridge.send("fake", "hello")
        assert result is True
        fake = bridge._channels["fake"]
        assert fake.sent[-1]["content"] == "hello"


class TestCommandParsing:
    def test_help_command(self, bridge):
        reply = bridge.handle_incoming("user1", "/help", "fake")
        assert "agents" in reply.lower()
        assert "notify" in reply.lower()

    def test_notify_command(self, bridge, store):
        reply = bridge.handle_incoming("user1", "/notify slack", "fake")
        assert "slack" in reply.lower()
        session = store.get_or_create("user1", "fake")
        assert session["preferred_notification_channel"] == "slack"

    def test_agents_command(self, bridge):
        bridge._agent_manager = MagicMock()
        bridge._agent_manager.list_agents.return_value = []
        reply = bridge.handle_incoming("user1", "/agents", "fake")
        assert "no" in reply.lower() or "agent" in reply.lower()

    def test_unknown_command_falls_through_to_chat(self, bridge, mock_system):
        bridge.handle_incoming("user1", "/unknown_cmd", "fake")
        # Should treat as regular chat
        mock_system.ask.assert_called_once()

    def test_more_command_returns_pending(self, bridge, store):
        store.get_or_create("user1", "fake")
        store.set_pending_response("user1", "fake", "the rest of the long response")
        reply = bridge.handle_incoming("user1", "/more", "fake")
        assert "the rest of the long response" in reply


class TestChatRouting:
    def test_routes_to_system_ask(self, bridge, mock_system):
        reply = bridge.handle_incoming("user1", "what is 2+2?", "fake")
        mock_system.ask.assert_called_once()
        call_kwargs = mock_system.ask.call_args
        assert "2+2" in str(call_kwargs)
        assert reply == "Hello from Jarvis!"

    def test_stores_conversation_history(self, bridge, store, mock_system):
        bridge.handle_incoming("user1", "hello", "fake")
        session = store.get_or_create("user1", "fake")
        # user + assistant
        assert len(session["conversation_history"]) == 2
        assert session["conversation_history"][0]["role"] == "user"
        assert session["conversation_history"][1]["role"] == "assistant"

    def test_error_returns_friendly_message(self, bridge, mock_system):
        mock_system.ask.side_effect = RuntimeError("engine down")
        reply = bridge.handle_incoming("user1", "hello", "fake")
        assert "sorry" in reply.lower() or "couldn't" in reply.lower()


class TestResponseFormatting:
    def test_truncates_long_sms_response(self, bridge, mock_system):
        mock_system.ask.return_value = {"content": "x" * 2000}
        reply = bridge.handle_incoming(
            "user1",
            "tell me a story",
            "fake",
            max_length=1600,
        )
        assert len(reply) <= 1600
        assert "/more" in reply

    def test_short_response_not_truncated(self, bridge, mock_system):
        mock_system.ask.return_value = {"content": "short answer"}
        reply = bridge.handle_incoming("user1", "hi", "fake")
        assert reply == "short answer"
        assert "/more" not in reply
