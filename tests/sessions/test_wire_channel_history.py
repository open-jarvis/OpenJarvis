"""Tests for wire_channel session history"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus
from openjarvis.core.types import Role
from openjarvis.system import JarvisSystem


@pytest.fixture()
def minimal_system():
    engine = MagicMock()
    engine.generate.return_value = {"content": "ok", "usage": {}}
    return JarvisSystem(
        config=JarvisConfig(),
        bus=EventBus(),
        engine=engine,
        engine_key="mock",
        model="mock-model",
        agent_name="none",
    )


class TestWireChannelHistory:
    def test_prior_messages_passed_to_ask(self, tmp_path, minimal_system):
        """Session history is forwarded as prior_messages to ask()."""
        from openjarvis.sessions.session import SessionStore

        db = tmp_path / "sessions.db"
        store = SessionStore(db_path=db)
        minimal_system.session_store = store

        session_key = "telegram:chat123"
        session = store.get_or_create(
            session_key, channel="telegram", channel_user_id="u1"
        )
        store.save_message(session.session_id, "user", "hello", channel="telegram")
        store.save_message(
            session.session_id, "assistant", "hi there", channel="telegram"
        )

        captured: list = []

        def capturing_ask(query, **kwargs):
            captured.append(kwargs.get("prior_messages", []))
            return {"content": "reply"}

        minimal_system.ask = capturing_ask

        bridge = MagicMock()
        handler_ref: list = []

        def capture_handler(fn):
            handler_ref.append(fn)

        bridge.on_message = capture_handler
        minimal_system.wire_channel(bridge)

        cm = SimpleNamespace(
            channel="telegram",
            conversation_id="chat123",
            sender="u1",
            content="second message",
        )
        handler_ref[0](cm)

        assert len(captured) == 1
        msgs = captured[0]
        assert len(msgs) == 2
        assert msgs[0].role == Role.USER
        assert msgs[0].content == "hello"
        assert msgs[1].role == Role.ASSISTANT
        assert msgs[1].content == "hi there"

    def test_empty_session_passes_empty_prior_messages(self, tmp_path, minimal_system):
        """First message in a new session passes prior_messages=[]."""
        from openjarvis.sessions.session import SessionStore

        db = tmp_path / "sessions.db"
        store = SessionStore(db_path=db)
        minimal_system.session_store = store

        captured: list = []

        def capturing_ask(query, **kwargs):
            captured.append(kwargs.get("prior_messages", None))
            return {"content": "reply"}

        minimal_system.ask = capturing_ask

        bridge = MagicMock()
        handler_ref: list = []

        def capture_handler(fn):
            handler_ref.append(fn)

        bridge.on_message = capture_handler
        minimal_system.wire_channel(bridge)

        cm = SimpleNamespace(
            channel="telegram",
            conversation_id="new-chat",
            sender="u2",
            content="first message",
        )
        handler_ref[0](cm)

        assert len(captured) == 1
        assert captured[0] == []
