"""Tests for channel session store."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openjarvis.server.session_store import SessionStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = SessionStore(db_path=str(Path(tmpdir) / "sessions.db"))
        yield s
        s.close()


class TestGetOrCreate:
    def test_creates_new_session(self, store):
        session = store.get_or_create("user123", "twilio")
        assert session["sender_id"] == "user123"
        assert session["channel_type"] == "twilio"
        assert session["conversation_history"] == []
        assert session["preferred_notification_channel"] is None
        assert session["pending_response"] is None

    def test_returns_existing_session(self, store):
        store.get_or_create("user123", "twilio")
        store.append_message("user123", "twilio", "user", "hello")
        session = store.get_or_create("user123", "twilio")
        assert len(session["conversation_history"]) == 1

    def test_separate_sessions_per_channel(self, store):
        store.get_or_create("user123", "twilio")
        store.get_or_create("user123", "slack")
        store.append_message("user123", "twilio", "user", "hello via sms")
        twilio_session = store.get_or_create("user123", "twilio")
        slack_session = store.get_or_create("user123", "slack")
        assert len(twilio_session["conversation_history"]) == 1
        assert len(slack_session["conversation_history"]) == 0


class TestAppendMessage:
    def test_appends_message(self, store):
        store.get_or_create("user1", "slack")
        store.append_message("user1", "slack", "user", "hi")
        store.append_message("user1", "slack", "assistant", "hello!")
        session = store.get_or_create("user1", "slack")
        assert len(session["conversation_history"]) == 2
        assert session["conversation_history"][0] == {
            "role": "user",
            "content": "hi",
        }
        assert session["conversation_history"][1] == {
            "role": "assistant",
            "content": "hello!",
        }

    def test_caps_history_at_max_turns(self, store):
        store.get_or_create("user1", "slack")
        for i in range(25):
            store.append_message("user1", "slack", "user", f"msg {i}")
        session = store.get_or_create("user1", "slack")
        assert len(session["conversation_history"]) == 20
        assert session["conversation_history"][0]["content"] == "msg 5"


class TestNotificationPreference:
    def test_set_and_get(self, store):
        store.get_or_create("user1", "twilio")
        store.set_notification_preference("user1", "twilio", "slack")
        session = store.get_or_create("user1", "twilio")
        assert session["preferred_notification_channel"] == "slack"


class TestPendingResponse:
    def test_set_and_get(self, store):
        store.get_or_create("user1", "twilio")
        store.set_pending_response("user1", "twilio", "full long response text here")
        session = store.get_or_create("user1", "twilio")
        assert session["pending_response"] == "full long response text here"

    def test_clear_pending(self, store):
        store.get_or_create("user1", "twilio")
        store.set_pending_response("user1", "twilio", "some text")
        store.clear_pending_response("user1", "twilio")
        session = store.get_or_create("user1", "twilio")
        assert session["pending_response"] is None


class TestExpireSessions:
    def test_expire_clears_old_history(self, store):
        store.get_or_create("user1", "twilio")
        store.append_message("user1", "twilio", "user", "old message")
        # Force the updated_at to be old
        store._db.execute(
            "UPDATE channel_sessions SET updated_at = datetime('now', '-25 hours')"
        )
        store._db.commit()
        store.expire_sessions(max_age_hours=24)
        session = store.get_or_create("user1", "twilio")
        assert session["conversation_history"] == []


class TestLastActiveChannel:
    def test_returns_most_recent(self, store):
        store.get_or_create("user1", "twilio")
        store.get_or_create("user1", "slack")
        store.append_message("user1", "slack", "user", "latest")
        result = store.get_last_active_channel("user1")
        assert result == "slack"

    def test_returns_none_for_unknown_user(self, store):
        assert store.get_last_active_channel("nobody") is None
