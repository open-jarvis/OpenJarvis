"""Tests for between-turn completion notifications."""

from __future__ import annotations

from openjarvis.cli._bg_state import BgStatus
from openjarvis.cli._chat_notifications import NotificationDispatcher


def test_no_notifications_when_unchanged() -> None:
    initial = BgStatus(rust_extension="pending", models={"a": "downloading"})
    later = BgStatus(rust_extension="pending", models={"a": "downloading"})
    d = NotificationDispatcher(initial)
    msgs = d.diff(later)
    assert msgs == []


def test_notifies_when_rust_becomes_ready() -> None:
    initial = BgStatus(rust_extension="pending")
    later = BgStatus(rust_extension="ready")
    d = NotificationDispatcher(initial)
    msgs = d.diff(later)
    assert len(msgs) == 1
    assert "Rust extension" in msgs[0]
    assert "ready" in msgs[0].lower()


def test_notifies_when_model_becomes_ready() -> None:
    initial = BgStatus(models={"qwen3.5:9b": "downloading"})
    later = BgStatus(models={"qwen3.5:9b": "ready"})
    d = NotificationDispatcher(initial)
    msgs = d.diff(later)
    assert any("qwen3.5:9b" in m and "ready" in m.lower() for m in msgs)


def test_notifies_when_failed() -> None:
    initial = BgStatus(rust_extension="pending")
    later = BgStatus(rust_extension="failed", rust_error="x")
    d = NotificationDispatcher(initial)
    msgs = d.diff(later)
    assert any("failed" in m.lower() for m in msgs)


def test_does_not_renotify_in_same_session() -> None:
    """Once a transition has been reported, don't fire again."""
    initial = BgStatus(rust_extension="pending")
    d = NotificationDispatcher(initial)
    msgs1 = d.diff(BgStatus(rust_extension="ready"))
    assert len(msgs1) == 1
    msgs2 = d.diff(BgStatus(rust_extension="ready"))
    assert msgs2 == []
