"""Tests for the GoogleChatChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.google_chat import GoogleChatChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_google_chat():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("google_chat"):
        ChannelRegistry.register_value("google_chat", GoogleChatChannel)


class TestRegistration:
    def test_registry_key(self):
        assert ChannelRegistry.contains("google_chat")

    def test_channel_id(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )
        assert ch.channel_id == "google_chat"


class TestInit:
    def test_defaults(self):
        ch = GoogleChatChannel()
        assert ch._webhook_url == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_url(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )
        assert (
            ch._webhook_url
            == "https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )

    def test_env_var_fallback(self):
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CHAT_WEBHOOK_URL": "https://chat.googleapis.com/v1/spaces/env/messages?key=env",
            },
        ):
            ch = GoogleChatChannel()
            assert (
                ch._webhook_url
                == "https://chat.googleapis.com/v1/spaces/env/messages?key=env"
            )

    def test_constructor_overrides_env(self):
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CHAT_WEBHOOK_URL": "https://chat.googleapis.com/v1/spaces/env/messages?key=env",
            },
        ):
            ch = GoogleChatChannel(
                webhook_url="https://chat.googleapis.com/v1/spaces/explicit/messages?key=explicit"
            )
            assert (
                ch._webhook_url
                == "https://chat.googleapis.com/v1/spaces/explicit/messages?key=explicit"
            )


class TestSend:
    def test_send_success(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("space", "Hello!")
            assert result is True
            mock_post.assert_called_once()

    def test_send_failure(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("space", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("space", "Hello!")
            assert result is False

    def test_send_no_url(self):
        ch = GoogleChatChannel()
        result = ch.send("space", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy",
            bus=bus,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response):
            ch.send("space", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestListChannels:
    def test_list_channels(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )
        assert ch.list_channels() == ["google_chat"]


class TestStatus:
    def test_disconnected_initially(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_no_url_connect_error(self):
        ch = GoogleChatChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR


class TestOnMessage:
    def test_on_message(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )
        handler = MagicMock()
        ch.on_message(handler)
        assert handler in ch._handlers


class TestDisconnect:
    def test_disconnect(self):
        ch = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/xxx/messages?key=yyy"
        )
        ch._status = ChannelStatus.CONNECTED
        ch.disconnect()
        assert ch.status() == ChannelStatus.DISCONNECTED
