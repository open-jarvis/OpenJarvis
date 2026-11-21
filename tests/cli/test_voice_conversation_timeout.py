"""Conversation mode must not listen forever after a single wake word."""

from __future__ import annotations

from openjarvis.cli._voice_chat import VoiceSession


def _session(timeout: float = 30.0) -> VoiceSession:
    class _Speech:
        conversation_timeout_seconds = timeout

    class _Config:
        speech = _Speech()

    return VoiceSession(_Config())


def test_conversation_expires_after_timeout(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(
        "openjarvis.cli._voice_chat.time.monotonic", lambda: now[0]
    )
    session = _session(30.0)

    session.enter_conversation()
    assert session.conversation_active

    now[0] = 1029.0
    assert session.conversation_active

    now[0] = 1031.0
    assert not session.conversation_active
    assert not session.conversation_active  # idempotent


def test_touch_renews_the_deadline(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(
        "openjarvis.cli._voice_chat.time.monotonic", lambda: now[0]
    )
    session = _session(30.0)

    session.enter_conversation()
    now[0] = 1020.0
    session.touch_conversation()

    now[0] = 1045.0
    assert session.conversation_active
    now[0] = 1051.0
    assert not session.conversation_active


def test_leave_conversation_clears_state(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(
        "openjarvis.cli._voice_chat.time.monotonic", lambda: now[0]
    )
    session = _session(30.0)
    session.enter_conversation()
    session.leave_conversation()
    assert not session.conversation_active


def test_speech_config_has_safe_defaults() -> None:
    from openjarvis.core.config import JarvisConfig

    config = JarvisConfig()
    assert 0.5 <= config.speech.wake_word_threshold <= 1.0
    assert config.speech.conversation_timeout_seconds >= 5.0
