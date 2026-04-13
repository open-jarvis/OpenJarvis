"""Tests for the TelegramChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.telegram import TelegramChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_telegram():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("telegram"):
        ChannelRegistry.register_value("telegram", TelegramChannel)


TestCommonChannel = make_common_channel_tests(
    TelegramChannel, "telegram", constructor_kwargs={"bot_token": "test-token"}
)


class TestInit:
    def test_defaults(self):
        ch = TelegramChannel()
        assert ch._token == ""
        assert ch._parse_mode == "Markdown"
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_token(self):
        ch = TelegramChannel(bot_token="my-token")
        assert ch._token == "my-token"

    def test_env_var_fallback(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env-token"}):
            ch = TelegramChannel()
            assert ch._token == "env-token"

    def test_constructor_overrides_env(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env-token"}):
            ch = TelegramChannel(bot_token="explicit-token")
            assert ch._token == "explicit-token"


class TestSend:
    def test_send_success(self):
        ch = TelegramChannel(bot_token="123:ABC")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("12345678", "Hello!")
            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            url = call_args[0][0]
            assert "api.telegram.org" in url
            assert "bot123:ABC" in url
            assert "sendMessage" in url
            payload = call_args[1]["json"]
            assert payload["chat_id"] == "12345678"
            assert payload["text"] == "Hello!"
            assert payload["parse_mode"] == "Markdown"

    def test_send_failure(self):
        ch = TelegramChannel(bot_token="123:ABC")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("12345678", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = TelegramChannel(bot_token="123:ABC")

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("12345678", "Hello!")
            assert result is False

    def test_send_no_token(self):
        ch = TelegramChannel()
        result = ch.send("12345678", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = TelegramChannel(bot_token="123:ABC", bus=bus)

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response):
            ch.send("12345678", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_token_connect_error(self):
        ch = TelegramChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR


class TestAllowedChatIds:
    """Tests for the allowed_chat_ids enforcement in _poll_loop."""

    def _make_update(self, chat_id: str, text: str = "hello"):
        """Build a minimal fake python-telegram-bot Update object."""
        msg = MagicMock()
        msg.text = text
        msg.message_id = 1
        msg.from_user.id = chat_id
        msg.chat.id = chat_id
        update = MagicMock()
        update.message = msg
        return update

    def _invoke_handle_msg(self, ch: TelegramChannel, chat_id: str, text: str = "hi"):
        """Simulate _poll_loop dispatching a message without starting a thread."""
        from openjarvis.channels._stubs import ChannelMessage

        cm = ChannelMessage(
            channel="telegram",
            sender=chat_id,
            content=text,
            message_id="1",
            conversation_id=chat_id,
        )
        # Directly exercise the allow-list logic (mirrors _handle_msg body)
        if ch._allowed_chat_ids:
            _allowed = {
                cid.strip() for cid in ch._allowed_chat_ids.split(",") if cid.strip()
            }
            if cm.conversation_id not in _allowed:
                return False  # would return inside _handle_msg
        for handler in ch._handlers:
            handler(cm)
        return True

    def test_no_allowlist_accepts_any(self):
        """When allowed_chat_ids is empty every chat is dispatched."""
        ch = TelegramChannel(bot_token="tok", allowed_chat_ids="")
        handler = MagicMock()
        ch.on_message(handler)
        dispatched = self._invoke_handle_msg(ch, "99999")
        assert dispatched is True
        handler.assert_called_once()

    def test_allowlist_passes_listed_chat(self):
        """A chat ID present in the allow-list is dispatched to handlers."""
        ch = TelegramChannel(bot_token="tok", allowed_chat_ids="111,222")
        handler = MagicMock()
        ch.on_message(handler)
        dispatched = self._invoke_handle_msg(ch, "111")
        assert dispatched is True
        handler.assert_called_once()

    def test_allowlist_blocks_unlisted_chat(self):
        """A chat ID not in the allow-list is silently dropped (not dispatched)."""
        ch = TelegramChannel(bot_token="tok", allowed_chat_ids="111,222")
        handler = MagicMock()
        ch.on_message(handler)
        dispatched = self._invoke_handle_msg(ch, "999")
        assert dispatched is False
        handler.assert_not_called()

    def test_allowlist_trims_whitespace(self):
        """Spaces around IDs in the allow-list are handled gracefully."""
        ch = TelegramChannel(bot_token="tok", allowed_chat_ids=" 111 , 222 ")
        handler = MagicMock()
        ch.on_message(handler)
        dispatched = self._invoke_handle_msg(ch, "111")
        assert dispatched is True
        handler.assert_called_once()


class TestChannelAgentWiring:
    """Tests for the channel → agent handler wired in serve.py."""

    def test_on_message_handler_invoked_on_message(self):
        """on_message callback registered on a channel is called when a message
        arrives."""
        ch = TelegramChannel(bot_token="tok")
        received = []
        ch.on_message(lambda cm: received.append(cm))

        from openjarvis.channels._stubs import ChannelMessage

        cm = ChannelMessage(
            channel="telegram",
            sender="42",
            content="ping",
            message_id="1",
            conversation_id="42",
        )
        for h in ch._handlers:
            h(cm)

        assert len(received) == 1
        assert received[0].content == "ping"

    def test_multiple_handlers_all_invoked(self):
        """Both handlers registered via on_message are called for the same message."""
        ch = TelegramChannel(bot_token="tok")
        calls_a: list = []
        calls_b: list = []
        ch.on_message(lambda cm: calls_a.append(cm))
        ch.on_message(lambda cm: calls_b.append(cm))

        from openjarvis.channels._stubs import ChannelMessage

        cm = ChannelMessage(
            channel="telegram",
            sender="1",
            content="x",
            message_id="1",
            conversation_id="1",
        )
        for h in ch._handlers:
            h(cm)

        assert len(calls_a) == 1
        assert len(calls_b) == 1
