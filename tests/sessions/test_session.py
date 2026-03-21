"""Tests for session management (Phase 15.4)."""

from __future__ import annotations

import time

from openjarvis.sessions.session import (
    Session,
    SessionIdentity,
    SessionStore,
)


class TestSession:
    def test_create_session(self):
        session = Session(session_id="s1")
        assert session.session_id == "s1"
        assert len(session.messages) == 0

    def test_add_message(self):
        session = Session(session_id="s1")
        session.add_message("user", "Hello")
        assert len(session.messages) == 1
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "Hello"
        assert session.last_activity > 0


class TestSessionIdentity:
    def test_create_identity(self):
        identity = SessionIdentity(
            user_id="u1",
            display_name="Alice",
            channel_ids={"telegram": "t123"},
        )
        assert identity.user_id == "u1"
        assert identity.channel_ids["telegram"] == "t123"


class TestSessionStore:
    def _make_store(self, tmp_path, **kwargs):
        return SessionStore(db_path=tmp_path / "sessions.db", **kwargs)

    def test_create_session(self, tmp_path):
        store = self._make_store(tmp_path)
        session = store.get_or_create("user1", display_name="Alice")
        assert session.session_id != ""
        assert session.identity is not None
        assert session.identity.user_id == "user1"
        store.close()

    def test_get_existing_session(self, tmp_path):
        store = self._make_store(tmp_path)
        s1 = store.get_or_create("user1")
        s2 = store.get_or_create("user1")
        assert s1.session_id == s2.session_id
        store.close()

    def test_save_message(self, tmp_path):
        store = self._make_store(tmp_path)
        session = store.get_or_create("user1")
        store.save_message(session.session_id, "user", "Hello")
        store.save_message(session.session_id, "assistant", "Hi there!")

        # Reload session
        reloaded = store.get_or_create("user1")
        assert len(reloaded.messages) == 2
        assert reloaded.messages[0].content == "Hello"
        assert reloaded.messages[1].content == "Hi there!"
        store.close()

    def test_link_channel(self, tmp_path):
        store = self._make_store(tmp_path)
        session = store.get_or_create("user1")
        store.link_channel(session.session_id, "telegram", "t123")
        store.link_channel(session.session_id, "discord", "d456")

        reloaded = store.get_or_create("user1")
        assert reloaded.identity.channel_ids.get("telegram") == "t123"
        assert reloaded.identity.channel_ids.get("discord") == "d456"
        store.close()

    def test_session_expiry(self, tmp_path):
        store = self._make_store(tmp_path, max_age_hours=0.0001)  # ~0.36 seconds
        s1 = store.get_or_create("user1")
        time.sleep(0.5)
        s2 = store.get_or_create("user1")
        assert s1.session_id != s2.session_id
        store.close()

    def test_decay(self, tmp_path):
        store = self._make_store(tmp_path, max_age_hours=0.0001)
        store.get_or_create("user1")
        time.sleep(0.5)
        removed = store.decay()
        assert removed >= 1
        store.close()

    def test_list_sessions(self, tmp_path):
        store = self._make_store(tmp_path)
        store.get_or_create("user1")
        store.get_or_create("user2")
        sessions = store.list_sessions()
        assert len(sessions) == 2
        store.close()

    def test_consolidation(self, tmp_path):
        store = self._make_store(tmp_path, consolidation_threshold=5)
        session = store.get_or_create("user1")
        for i in range(10):
            store.save_message(session.session_id, "user", f"msg {i}")
        # After saving 10 messages with threshold=5, consolidation should trigger
        reloaded = store.get_or_create("user1")
        # Messages should be fewer after consolidation
        assert len(reloaded.messages) < 10
        store.close()

    def test_cross_channel_session(self, tmp_path):
        store = self._make_store(tmp_path)
        s1 = store.get_or_create("user1", channel="telegram", channel_user_id="t1")
        store.save_message(s1.session_id, "user", "From Telegram", channel="telegram")
        store.link_channel(s1.session_id, "discord", "d1")
        store.save_message(s1.session_id, "user", "From Discord", channel="discord")

        reloaded = store.get_or_create("user1")
        assert len(reloaded.messages) == 2
        assert reloaded.messages[0].channel == "telegram"
        assert reloaded.messages[1].channel == "discord"
        store.close()
