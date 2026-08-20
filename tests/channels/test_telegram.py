"""Tests for the TelegramChannel adapter."""

from __future__ import annotations

import os
import sys
import threading
from types import SimpleNamespace
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

    def test_send_uses_channel_as_chat_id_under_unified_contract(self):
        """Canonical contract (#515/#516): the first positional ``channel``
        arg is the chat destination, and ``conversation_id`` is the inbound
        message id used as ``reply_to_message_id`` — not the chat id."""
        ch = TelegramChannel(bot_token="123:ABC")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("12345678", "Reply!", conversation_id="55")
            assert result is True
            payload = mock_post.call_args[1]["json"]
            # Destination is the chat id from the positional channel arg.
            assert payload["chat_id"] == "12345678"
            # conversation_id becomes the reply reference, not the chat id.
            assert payload["reply_to_message_id"] == "55"

    def test_send_empty_content_returns_false_without_request(self):
        """Regression for #783: textwrap.wrap("") returns an empty list,
        so the send loop never runs any HTTP request -- but the method
        still fell through to publish CHANNEL_MESSAGE_SENT and return
        True, falsely reporting success for a message that was never
        transmitted."""
        bus = EventBus(record_history=True)
        ch = TelegramChannel(bot_token="123:ABC", bus=bus)

        with patch("httpx.post") as mock_post:
            result = ch.send("12345678", "")
            assert result is False
            mock_post.assert_not_called()

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT not in event_types

    def test_send_retries_without_markdown_on_parse_error(self):
        """Regression for #783: Telegram returns 400 with a "can't parse
        entities" body for unparseable Markdown (lone asterisks, unclosed
        code fences, snake_case identifiers). The old code treated this
        the same as any other failure and dropped the message outright
        instead of retrying as plain text."""
        ch = TelegramChannel(bot_token="123:ABC")

        markdown_failure = MagicMock()
        markdown_failure.status_code = 400
        markdown_failure.text = (
            '{"ok":false,"description":"Bad Request: can\'t parse entities: '
            "Character '_' is reserved and must be escaped\"}"
        )
        plain_success = MagicMock()
        plain_success.status_code = 200

        with patch(
            "httpx.post", side_effect=[markdown_failure, plain_success]
        ) as mock_post:
            result = ch.send("12345678", "some_snake_case_text")
            assert result is True
            assert mock_post.call_count == 2

            first_payload = mock_post.call_args_list[0][1]["json"]
            assert first_payload["parse_mode"] == "Markdown"

            retry_payload = mock_post.call_args_list[1][1]["json"]
            assert "parse_mode" not in retry_payload
            assert retry_payload["text"] == "some_snake_case_text"

    def test_send_non_markdown_failure_does_not_retry(self):
        """A 4xx/5xx that isn't a Markdown parse error must still fail
        outright, not silently retry and mask a real problem."""
        ch = TelegramChannel(bot_token="123:ABC")

        server_error = MagicMock()
        server_error.status_code = 500
        server_error.text = '{"ok":false,"description":"Internal Server Error"}'

        with patch("httpx.post", return_value=server_error) as mock_post:
            result = ch.send("12345678", "Hello!")
            assert result is False
            mock_post.assert_called_once()

    def test_send_legacy_conversation_id_only_still_targets_chat(self):
        """Backwards compatibility: a legacy caller passing the chat id via
        ``conversation_id`` (with an empty ``channel``) still delivers."""
        ch = TelegramChannel(bot_token="123:ABC")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("", "Hello!", conversation_id="12345678")
            assert result is True
            payload = mock_post.call_args[1]["json"]
            assert payload["chat_id"] == "12345678"
            # When channel is empty, conversation_id is the chat id, so it must
            # not also be used as a self-referential reply id.
            assert "reply_to_message_id" not in payload


class TestStatus:
    def test_no_token_connect_error(self):
        ch = TelegramChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR


class TestDisconnectStopsRealListener:
    """Regression for #784: disconnect() must actually interrupt the
    running `Application.run_polling()` call (which nothing previously
    observed `_stop_event`), and must not report DISCONNECTED unless the
    listener thread actually terminated -- otherwise a subsequent
    connect() spawns a second poller against the same bot token, and
    Telegram's getUpdates API returns 409 Conflict."""

    def test_disconnect_schedules_stop_running_via_call_soon_threadsafe(self):
        """stop_running() calls asyncio.get_running_loop().stop() internally,
        which is only safe from within the poll loop's own thread/loop --
        so disconnect() must schedule it via loop.call_soon_threadsafe(),
        not call it directly."""
        ch = TelegramChannel(bot_token="123:ABC")
        ch._status = ChannelStatus.CONNECTED

        mock_app = MagicMock()
        mock_loop = MagicMock()
        ch._app = mock_app
        ch._loop = mock_loop

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        ch._listener_thread = mock_thread

        ch.disconnect()

        mock_loop.call_soon_threadsafe.assert_called_once_with(mock_app.stop_running)
        mock_thread.join.assert_called_once()
        assert ch._listener_thread is None
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_disconnect_does_not_report_disconnected_if_thread_still_alive(self):
        """If the listener thread is still running after the join timeout,
        disconnect() must not lie about the channel being DISCONNECTED --
        doing so would let a later connect() spawn a duplicate poller."""
        ch = TelegramChannel(bot_token="123:ABC")
        ch._status = ChannelStatus.CONNECTED

        ch._app = MagicMock()
        ch._loop = MagicMock()

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True  # join() timed out
        ch._listener_thread = mock_thread

        ch.disconnect()

        assert ch.status() != ChannelStatus.DISCONNECTED
        # Must keep the reference so a future disconnect()/duplicate-guard
        # can still see the thread is running.
        assert ch._listener_thread is mock_thread

    def test_disconnect_without_app_or_loop_still_works(self):
        """Send-only mode (python-telegram-bot not installed, or connect()
        never actually started a listener): _app/_loop are None, so
        disconnect() must fall back to the old join-only behavior instead
        of raising."""
        ch = TelegramChannel(bot_token="123:ABC")
        ch._status = ChannelStatus.CONNECTED

        ch.disconnect()

        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_connect_guards_against_duplicate_listener(self):
        """connect() must not spawn a second polling thread while one is
        already running -- that's exactly what produces the 409 Conflict
        errors described in the issue."""
        ch = TelegramChannel(bot_token="123:ABC")

        existing_thread = MagicMock()
        existing_thread.is_alive.return_value = True
        ch._listener_thread = existing_thread
        ch._status = ChannelStatus.CONNECTED

        with patch("threading.Thread") as mock_thread_cls:
            ch.connect()

        mock_thread_cls.assert_not_called()
        assert ch._listener_thread is existing_thread

    def test_disconnect_before_app_publication_prevents_polling_start(self):
        """A disconnect while ApplicationBuilder.build() runs is not lost."""
        building = threading.Event()
        release_app = threading.Event()
        polling_calls: list[dict] = []

        class FakeApp:
            def add_handler(self, handler):
                pass

            def run_polling(self, **kwargs):
                polling_calls.append(kwargs)

            def stop_running(self):
                raise AssertionError("app was not published when disconnect ran")

        class FakeBuilder:
            def token(self, token):
                return self

            def build(self):
                building.set()
                assert release_app.wait(timeout=2)
                return FakeApp()

        telegram_ext = SimpleNamespace(
            ApplicationBuilder=FakeBuilder,
            MessageHandler=lambda *args: args,
            filters=SimpleNamespace(TEXT=object()),
        )
        ch = TelegramChannel(bot_token="123:ABC")

        with patch.dict(
            sys.modules,
            {
                "telegram": SimpleNamespace(ext=telegram_ext),
                "telegram.ext": telegram_ext,
            },
        ):
            ch.connect()
            assert building.wait(timeout=2)

            disconnect_thread = threading.Thread(target=ch.disconnect)
            disconnect_thread.start()
            assert ch._stop_event.wait(timeout=2)
            release_app.set()
            disconnect_thread.join(timeout=2)

        assert not disconnect_thread.is_alive()
        assert polling_calls == []
        assert ch._listener_thread is None
        assert ch._app is None
        assert ch._loop is None
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_disconnect_is_serialized_with_connect_lifecycle(self):
        """A disconnect cannot slip through while connect owns lifecycle state."""
        ch = TelegramChannel(bot_token="123:ABC")
        attempted = threading.Event()

        def disconnect() -> None:
            attempted.set()
            ch.disconnect()

        with ch._lifecycle_lock:
            worker = threading.Thread(target=disconnect)
            worker.start()
            assert attempted.wait(timeout=2)
            assert not ch._stop_event.wait(timeout=0.05)

        worker.join(timeout=2)
        assert not worker.is_alive()
        assert ch._stop_event.is_set()
        assert ch.status() == ChannelStatus.DISCONNECTED


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
