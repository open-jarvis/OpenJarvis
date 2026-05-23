"""Execution-context propagation of the active trace_id.

The trace_id ties together every telemetry row and tool call that belongs to a
single agent run, so they can later be joined for Return-on-Cognitive-Spend
analysis (energy and cost per validated outcome).

Uses :class:`contextvars.ContextVar` so the value propagates across
``asyncio.create_task`` and ``run_in_executor`` boundaries automatically — the
voice loop and any other async/threaded code paths keep the right trace_id
without explicit plumbing.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_CURRENT_TRACE_ID: ContextVar[str] = ContextVar("openjarvis_current_trace_id", default="")


def get_current_trace_id() -> str:
    """Return the trace_id for the currently executing trace, or ``""`` if none."""
    return _CURRENT_TRACE_ID.get()


def set_current_trace_id(trace_id: str) -> object:
    """Set the active trace_id. Returns a token for use with :func:`reset_current_trace_id`."""
    return _CURRENT_TRACE_ID.set(trace_id)


def reset_current_trace_id(token: object) -> None:
    """Reset the active trace_id using the token returned by :func:`set_current_trace_id`."""
    _CURRENT_TRACE_ID.reset(token)  # type: ignore[arg-type]


@contextmanager
def trace_scope(trace_id: str) -> Iterator[str]:
    """Set the active trace_id for the duration of the ``with`` block.

    Usage::

        with trace_scope(trace.trace_id):
            agent.run(...)  # all telemetry rows recorded here carry trace.trace_id
    """
    token = _CURRENT_TRACE_ID.set(trace_id)
    try:
        yield trace_id
    finally:
        _CURRENT_TRACE_ID.reset(token)


__all__ = [
    "get_current_trace_id",
    "set_current_trace_id",
    "reset_current_trace_id",
    "trace_scope",
]
