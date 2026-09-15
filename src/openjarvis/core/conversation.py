"""Which conversation the current call belongs to.

Tool instances are process-wide: one ``ToolExecutor`` serves every
conversation, and so does one ``ReplTool``. Anything a tool remembers between
calls therefore needs an explicit owner, or one customer inherits another's
working set -- the defect the ordering cart shipped with.

``ToolExecutor`` copies the caller's context before dispatching into its thread
pool, so a variable set here reaches the tool. Mirrors the existing
``presentation_generation`` scope in ``kiosk/presentation.py``.
"""

from __future__ import annotations

import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import Iterator

_CONVERSATION_ID: ContextVar[str] = ContextVar("openjarvis_conversation_id", default="")
_TURN_NONCE: ContextVar[str] = ContextVar("openjarvis_turn_nonce", default="")


@dataclass
class _TurnState:
    nonce: str
    active: bool = True
    claimed: bool = False


_TURN_STATE: ContextVar[_TurnState | None] = ContextVar(
    "openjarvis_turn_state", default=None
)
_TURN_LOCK = RLock()
_ACTIVE_TURNS: dict[str, _TurnState] = {}


def turn_nonce_is_active(nonce: str) -> bool:
    """Also invalidate copied worker contexts when their turn ends or is replaced."""
    with _TURN_LOCK:
        state = _TURN_STATE.get()
        return bool(
            state
            and state.active
            and state.nonce == nonce
            and _ACTIVE_TURNS.get(current_conversation_id()) is state
        )


def claim_turn_nonce(nonce: str) -> bool:
    """Consume a model's fresh checkout dispatch once within its owning turn."""
    with _TURN_LOCK:
        state = _TURN_STATE.get()
        if not turn_nonce_is_active(nonce) or state is None or state.claimed:
            return False
        state.claimed = True
        return True


def current_conversation_id() -> str:
    """Return the current conversation's id, or "" outside any conversation."""
    return _CONVERSATION_ID.get()


def current_turn_nonce() -> str:
    """Return the opaque nonce for the active agent turn, or ""."""
    return _TURN_NONCE.get()


@contextmanager
def agent_turn_scope() -> Iterator[str]:
    """Issue one unguessable nonce that expires with the current agent turn."""
    nonce = secrets.token_hex(16)
    state = _TurnState(nonce)
    owner = current_conversation_id()
    parent = _TURN_STATE.get()
    with _TURN_LOCK:
        _ACTIVE_TURNS[owner] = state
    state_token = _TURN_STATE.set(state)
    token = _TURN_NONCE.set(nonce)
    try:
        yield nonce
    finally:
        with _TURN_LOCK:
            state.active = False
            if _ACTIVE_TURNS.get(owner) is state:
                if parent is not None and parent.active:
                    _ACTIVE_TURNS[owner] = parent
                else:
                    _ACTIVE_TURNS.pop(owner, None)
        _TURN_STATE.reset(state_token)
        _TURN_NONCE.reset(token)


@contextmanager
def conversation_scope(conversation_id: str) -> Iterator[None]:
    """Own every tool working set created inside this block."""
    token = _CONVERSATION_ID.set(conversation_id)
    try:
        yield
    finally:
        _CONVERSATION_ID.reset(token)


__all__ = [
    "agent_turn_scope",
    "claim_turn_nonce",
    "conversation_scope",
    "current_conversation_id",
    "current_turn_nonce",
    "turn_nonce_is_active",
]
