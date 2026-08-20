"""Tests for the DiscordChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.discord_channel import DiscordChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_discord():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("discord"):
        ChannelRegistry.register_value("discord", DiscordChannel)


TestCommonChannel = make_common_channel_tests(
    DiscordChannel, "discord", constructor_kwargs={"bot_token": "test-token"}
)


class TestInit:
    def test_defaults(self):
        ch = DiscordChannel()
        assert ch._token == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_token(self):
        ch = DiscordChannel(bot_token="my-token")
        assert ch._token == "my-token"

    def test_env_var_fallback(self):
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "env-token"}):
            ch = DiscordChannel()
            assert ch._token == "env-token"

    def test_constructor_overrides_env(self):
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "env-token"}):
            ch = DiscordChannel(bot_token="explicit-token")
            assert ch._token == "explicit-token"


class TestSend:
    def test_send_success(self):
        ch = DiscordChannel(bot_token="my-bot-token")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("987654321", "Hello Discord!")
            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            url = call_args[0][0]
            assert "discord.com/api/v10/channels/987654321/messages" in url
            headers = call_args[1]["headers"]
            assert headers["Authorization"] == "Bot my-bot-token"
            payload = call_args[1]["json"]
            assert payload["content"] == "Hello Discord!"

    def test_send_with_conversation_id(self):
        ch = DiscordChannel(bot_token="my-bot-token")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            ch.send("987654321", "Reply!", conversation_id="msg-123")
            payload = mock_post.call_args[1]["json"]
            assert payload["message_reference"] == {"message_id": "msg-123"}

    def test_send_refuses_empty_channel(self):
        """Defensive guard for #459 follow-up: an empty `channel` arg
        would build /channels//messages and silently 404. We refuse
        fast so the upstream bug surfaces in the log instead of the
        reply being blackholed."""
        ch = DiscordChannel(bot_token="my-bot-token")
        with patch("httpx.post") as mock_post:
            result = ch.send("", "Hi there!")
            assert result is False
            mock_post.assert_not_called()

    def test_send_failure(self):
        ch = DiscordChannel(bot_token="my-bot-token")

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Missing Permissions"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("987654321", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = DiscordChannel(bot_token="my-bot-token")

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("987654321", "Hello!")
            assert result is False

    def test_send_no_token(self):
        ch = DiscordChannel()
        result = ch.send("987654321", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = DiscordChannel(bot_token="my-bot-token", bus=bus)

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response):
            ch.send("987654321", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_token_connect_error(self):
        ch = DiscordChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR


class TestWireChannelEndToEnd:
    """Regression for #515/#516 — the full inbound→reply path through
    JarvisSystem.wire_channel must call the real Discord REST API with the
    numeric channel id (not "discord") and a message_reference equal to the
    inbound message id (not the channel id).
    """

    def test_reply_hits_real_channel_id_and_message_reference(self, tmp_path):
        from openjarvis.channels._stubs import ChannelMessage
        from openjarvis.core.config import JarvisConfig
        from openjarvis.core.events import EventBus
        from openjarvis.system import JarvisSystem

        config = JarvisConfig()
        config.sessions.db_path = str(tmp_path / "sessions.db")
        from unittest.mock import MagicMock as _MM

        system = JarvisSystem(
            config=config,
            bus=EventBus(record_history=False),
            engine=_MM(),
            engine_key="mock",
            model="test-model",
            agent_name="",
        )
        system.ask = _MM(return_value={"content": "pong"})

        channel = DiscordChannel(bot_token="my-bot-token")
        system.wire_channel(channel)

        # Exactly the ChannelMessage shape DiscordChannel._gateway_loop emits:
        # channel = "discord" (TYPE label), conversation_id = numeric channel
        # id, message_id = numeric message id.
        cm = ChannelMessage(
            channel="discord",
            sender="user-1",
            content="hello",
            message_id="111122223333444455",
            conversation_id="987654321098765432",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("httpx.post", return_value=mock_response) as mock_post:
            # Invoke the handler wire_channel registered on the channel.
            for handler in channel._handlers:
                handler(cm)

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        # #515: destination is the numeric channel id, not the "discord" label.
        assert "discord.com/api/v10/channels/987654321098765432/messages" in url
        assert "channels/discord/messages" not in url
        payload = mock_post.call_args[1]["json"]
        assert payload["content"] == "pong"
        # #516: message_reference is the inbound message id, NOT the channel id.
        assert payload["message_reference"] == {"message_id": "111122223333444455"}
        assert payload["message_reference"]["message_id"] != "987654321098765432"
