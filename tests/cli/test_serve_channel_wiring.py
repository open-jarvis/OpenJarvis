"""Tests for JarvisSystem.wire_channel() — channel → agent routing.

These tests exercise wire_channel() on JarvisSystem directly. The serve.py
entrypoint now delegates all channel-wiring logic there.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.channels._stubs import ChannelMessage
from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus
from openjarvis.sessions.session import SessionStore
from openjarvis.system import JarvisSystem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel_message(
    channel: str = "telegram",
    sender: str = "42",
    content: str = "hello",
    conversation_id: str = "42",
) -> ChannelMessage:
    return ChannelMessage(
        channel=channel,
        sender=sender,
        content=content,
        message_id="1",
        conversation_id=conversation_id,
    )


def _make_system(engine=None, agent_name="", tmp_path=None) -> JarvisSystem:
    """Build a minimal JarvisSystem with mock engine for testing wire_channel."""
    config = JarvisConfig()
    if tmp_path is not None:
        config.sessions.db_path = str(tmp_path / "sessions.db")
    mock_engine = engine or MagicMock()
    return JarvisSystem(
        config=config,
        bus=EventBus(record_history=False),
        engine=mock_engine,
        engine_key="mock",
        model="test-model",
        agent_name=agent_name,
    )


def _fire(channel_mock, cm: ChannelMessage) -> None:
    """Invoke all registered on_message handlers as if the channel received cm."""
    for handler in channel_mock.on_message.call_args_list:
        handler[0][0](cm)


# ---------------------------------------------------------------------------
# Tests via JarvisSystem.wire_channel()
# ---------------------------------------------------------------------------


class TestWireChannelWithAgent:
    """wire_channel routes incoming messages through the agent and replies."""

    def test_ask_called_and_reply_sent(self, tmp_path):
        system = _make_system(agent_name="simple", tmp_path=tmp_path)
        # Patch ask() so we don't need a real engine/agent
        system.ask = MagicMock(return_value={"content": "pong"})

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)

        # Simulate an incoming message
        cm = _make_channel_message(content="ping")
        handler = mock_channel.on_message.call_args[0][0]
        handler(cm)

        system.ask.assert_called_once()
        assert system.ask.call_args[0][0] == "ping"
        # Canonical send contract (#515/#516): the destination is the real
        # per-adapter id (carried in ChannelMessage.conversation_id), not the
        # channel TYPE label, and the conversation_id kwarg is the inbound
        # message id used as a reply reference, not the channel id.
        mock_channel.send.assert_called_once_with(
            "42",
            "pong",
            conversation_id="1",
        )

    def test_session_store_created_lazily(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        assert system.session_store is None

        mock_channel = MagicMock()
        system.ask = MagicMock(return_value={"content": "ok"})
        system.wire_channel(mock_channel)

        handler = mock_channel.on_message.call_args[0][0]
        handler(_make_channel_message())

        assert system.session_store is not None

    def test_existing_session_store_reused(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        existing_store = SessionStore(db_path=tmp_path / "sessions.db")
        system.session_store = existing_store
        system.ask = MagicMock(return_value={"content": "ok"})

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)

        handler = mock_channel.on_message.call_args[0][0]
        handler(_make_channel_message())

        assert system.session_store is existing_store


class TestWireChannelWithEngine:
    """wire_channel falls back to engine when no agent is set."""

    def test_engine_path_used_when_no_agent(self, tmp_path):
        system = _make_system(agent_name="", tmp_path=tmp_path)
        system.ask = MagicMock(return_value={"content": "raw reply"})

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)

        handler = mock_channel.on_message.call_args[0][0]
        handler(_make_channel_message(content="hi"))

        # Canonical send contract (#515/#516): destination = real channel id
        # (from ChannelMessage.conversation_id), reply ref = inbound message id.
        mock_channel.send.assert_called_once_with(
            "42",
            "raw reply",
            conversation_id="1",
        )


class TestWireChannelCanonicalContract:
    """Regression for #515/#516 — wire_channel must dispatch the canonical
    send contract so each adapter receives the right destination/reply ids,
    regardless of the channel TYPE label.
    """

    def test_discord_uses_real_channel_id_not_type_label(self, tmp_path):
        """A Discord ChannelMessage (channel="discord" TYPE label,
        conversation_id=<numeric channel id>, message_id=<numeric msg id>)
        must reply to the numeric channel id, with the message id as the
        reply reference — never "discord" as destination (#515) and never the
        channel id as the message reference (#516).
        """
        system = _make_system(tmp_path=tmp_path)
        system.ask = MagicMock(return_value={"content": "pong"})

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]

        cm = ChannelMessage(
            channel="discord",
            sender="user-1",
            content="hello",
            message_id="111122223333444455",
            conversation_id="987654321098765432",
        )
        handler(cm)

        args, kwargs = mock_channel.send.call_args
        # Destination is the real Discord channel id, NOT the type label.
        assert args[0] == "987654321098765432"
        assert args[0] != "discord"
        # Reply reference is the inbound message id, NOT the channel id.
        assert kwargs["conversation_id"] == "111122223333444455"
        assert kwargs["conversation_id"] != "987654321098765432"

    def test_telegram_uses_chat_id_and_message_id(self, tmp_path):
        """Telegram must keep working under the unified contract: destination
        is the chat id (conversation_id), reply ref is the message id."""
        system = _make_system(tmp_path=tmp_path)
        system.ask = MagicMock(return_value={"content": "pong"})

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]

        cm = ChannelMessage(
            channel="telegram",
            sender="42",
            content="ping",
            message_id="55",
            conversation_id="12345678",
        )
        handler(cm)

        mock_channel.send.assert_called_once_with(
            "12345678",
            "pong",
            conversation_id="55",
        )

    def test_session_key_still_uses_conversation_id(self, tmp_path):
        """The fix must not change session isolation keying, which still uses
        ``<channel>:<conversation_id>``."""
        system = _make_system(tmp_path=tmp_path)
        system.ask = MagicMock(return_value={"content": "ok"})

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]

        cm = ChannelMessage(
            channel="discord",
            sender="u1",
            content="hi",
            message_id="msg-9",
            conversation_id="chan-7",
        )
        handler(cm)

        # Session was created under the channel:conversation_id key.
        session = system.session_store.get_or_create("discord:chan-7")
        assert any(m.content == "hi" for m in session.messages)


class TestWireChannelSessionIsolation:
    """Separate conversation_ids get independent sessions."""

    def test_two_chats_isolated(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        replies = {"111": "reply-A", "222": "reply-B"}
        system.ask = MagicMock(
            side_effect=lambda q, **kw: {"content": replies.get(q, "")}
        )

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]

        handler(_make_channel_message(content="111", conversation_id="111"))
        handler(_make_channel_message(content="222", conversation_id="222"))

        # Reload sessions — each chat must have only its own messages
        s1 = system.session_store.get_or_create("telegram:111")
        s2 = system.session_store.get_or_create("telegram:222")
        c1 = {m.content for m in s1.messages}
        c2 = {m.content for m in s2.messages}

        assert "111" in c1 and "222" not in c1
        assert "222" in c2 and "111" not in c2

    def test_same_chat_accumulates_history(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        system.ask = MagicMock(return_value={"content": "reply"})

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]

        handler(_make_channel_message(content="first"))
        handler(_make_channel_message(content="second"))

        session = system.session_store.get_or_create("telegram:42")
        contents = [m.content for m in session.messages]
        # user + assistant alternating for two turns
        assert contents.count("first") == 1
        assert contents.count("second") == 1


class TestWireChannelErrorHandling:
    """Handler sends a user-visible error message when ask() raises."""

    def test_error_reply_sent(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        system.ask = MagicMock(side_effect=RuntimeError("boom"))

        mock_channel = MagicMock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]
        handler(_make_channel_message())

        mock_channel.send.assert_called_once()
        sent_content = mock_channel.send.call_args[0][1]
        assert "error" in sent_content.lower()


class TestChannelToolLoading:
    """JarvisSystem receives tools when agent accepts them."""

    def test_tool_using_agent_receives_tools(self, tmp_path):
        """JarvisSystem built with a tool list passes tools to the agent via ask()."""
        from openjarvis.tools._stubs import BaseTool, ToolSpec

        # Minimal fake tool
        class _FakeTool(BaseTool):
            spec = ToolSpec(name="fake", description="", parameters={})

            def execute(self, **_):  # type: ignore[override]
                pass

        fake_tool = _FakeTool()
        config = JarvisConfig()
        config.sessions.db_path = str(tmp_path / "sessions.db")

        system = JarvisSystem(
            config=config,
            bus=EventBus(record_history=False),
            engine=MagicMock(),
            engine_key="mock",
            model="test-model",
            agent_name="simple",
            tools=[fake_tool],
        )

        assert len(system.tools) == 1
        assert system.tools[0].spec.name == "fake"

    def test_non_tool_agent_receives_empty_tools(self, tmp_path):
        """JarvisSystem with no tools list results in empty tools — simple agent
        unaffected."""
        config = JarvisConfig()
        config.sessions.db_path = str(tmp_path / "sessions.db")

        system = JarvisSystem(
            config=config,
            bus=EventBus(record_history=False),
            engine=MagicMock(),
            engine_key="mock",
            model="test-model",
            agent_name="simple",
        )

        assert system.tools == []


class TestPerChatSessionIsolation:
    """Direct SessionStore isolation tests (not via wire_channel)."""

    def test_two_chats_have_separate_sessions(self, tmp_path):
        store = SessionStore(db_path=tmp_path / "sessions.db")

        session_a = store.get_or_create(
            "telegram:111",
            channel="telegram",
            channel_user_id="111",
        )
        store.save_message(session_a.session_id, "user", "msg from A")

        session_b = store.get_or_create(
            "telegram:222",
            channel="telegram",
            channel_user_id="222",
        )
        store.save_message(session_b.session_id, "user", "msg from B")

        reloaded_a = store.get_or_create(
            "telegram:111",
            channel="telegram",
            channel_user_id="111",
        )
        reloaded_b = store.get_or_create(
            "telegram:222",
            channel="telegram",
            channel_user_id="222",
        )

        contents_a = {m.content for m in reloaded_a.messages}
        contents_b = {m.content for m in reloaded_b.messages}

        assert "msg from A" in contents_a and "msg from B" not in contents_a
        assert "msg from B" in contents_b and "msg from A" not in contents_b

    def test_same_chat_accumulates_history(self, tmp_path):
        store = SessionStore(db_path=tmp_path / "sessions.db")
        session = store.get_or_create(
            "telegram:42",
            channel="telegram",
            channel_user_id="42",
        )
        store.save_message(session.session_id, "user", "first")
        store.save_message(session.session_id, "assistant", "reply")

        reloaded = store.get_or_create(
            "telegram:42",
            channel="telegram",
            channel_user_id="42",
        )
        assert [m.content for m in reloaded.messages] == ["first", "reply"]
