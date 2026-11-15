"""Global push-to-talk hotkey (optional ``keyboard`` dependency).

Alternative activation for voice chat: hold/press a hotkey instead of saying
the wake word. The ``keyboard`` package is optional — when it is missing the
caller falls back to the wake-word flow with a hint.
"""

from __future__ import annotations

import importlib.util


def hotkey_available() -> bool:
    """True when the ``keyboard`` package is importable (no slow import)."""
    return importlib.util.find_spec("keyboard") is not None


def wait_for_hotkey(key: str = "f8") -> bool:
    """Block until *key* is pressed.

    Returns ``False`` when ``keyboard`` is unavailable or the wait failed —
    callers fall back to the wake-word flow. Never raises.
    """
    try:
        import keyboard
    except ImportError:
        return False
    try:
        keyboard.wait(key)
        return True
    except Exception:  # noqa: BLE001 — best-effort input listener
        return False


__all__ = ["hotkey_available", "wait_for_hotkey"]
