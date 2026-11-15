"""Tests for the global push-to-talk hotkey helper."""

from __future__ import annotations

import sys

from openjarvis.speech.hotkey import hotkey_available, wait_for_hotkey


def test_wait_for_hotkey_returns_false_without_keyboard(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "keyboard", None)
    assert wait_for_hotkey() is False


def test_hotkey_available_without_keyboard(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "keyboard", None)
    assert hotkey_available() is False


def test_wait_for_hotkey_detects_press(monkeypatch) -> None:
    import types

    fake = types.SimpleNamespace(
        wait=lambda key: None,  # returns immediately = pressed
    )
    monkeypatch.setitem(sys.modules, "keyboard", fake)
    assert wait_for_hotkey("f8") is True


def test_wait_for_hotkey_survives_listener_errors(monkeypatch) -> None:
    import types

    def broken_wait(key):
        raise OSError("no keyboard device")

    fake = types.SimpleNamespace(wait=broken_wait)
    monkeypatch.setitem(sys.modules, "keyboard", fake)
    assert wait_for_hotkey() is False
