from __future__ import annotations

from unittest.mock import MagicMock
from openjarvis.core.types import Message, Role


def test_session_expiry_flushes_when_enough_turns():
    from openjarvis.daemon.session_expiry import SessionExpiryHook

    executor = MagicMock()
    executor.run_ephemeral.return_value = MagicMock(content="Saved 2 memories.")

    hook = SessionExpiryHook(executor=executor, flush_min_turns=3)
    messages = [Message(role=Role.USER, content=f"msg {i}") for i in range(5)]
    hook.on_session_expiry(session_id="test-session", messages=messages)

    executor.run_ephemeral.assert_called_once()


def test_session_expiry_skips_short_sessions():
    from openjarvis.daemon.session_expiry import SessionExpiryHook

    executor = MagicMock()
    hook = SessionExpiryHook(executor=executor, flush_min_turns=6)
    messages = [Message(role=Role.USER, content="hi")]
    hook.on_session_expiry(session_id="test-session", messages=messages)

    executor.run_ephemeral.assert_not_called()
