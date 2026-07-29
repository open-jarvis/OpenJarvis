"""Asynchronous contract implemented by all Codex backends."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from openjarvis.codex.types import (
    BackendCapabilities,
    BackendThread,
    BackendTurn,
    CodexEvent,
    CodexHealth,
    ThreadForkRequest,
    ThreadResumeRequest,
    ThreadStartRequest,
    TurnStartRequest,
)


@runtime_checkable
class CodexBackend(Protocol):
    """Common lifecycle for SDK, app-server, and degraded CLI transports."""

    @property
    def capabilities(self) -> BackendCapabilities:
        """Return the backend's explicit capability matrix."""

    async def health(self) -> CodexHealth:
        """Return credential-safe availability and authentication state."""

    async def start_thread(self, request: ThreadStartRequest) -> BackendThread:
        """Create and persist a non-ephemeral thread."""

    async def resume_thread(self, request: ThreadResumeRequest) -> BackendThread:
        """Resume a thread by explicit id or persisted task/session mapping."""

    async def fork_thread(self, request: ThreadForkRequest) -> BackendThread:
        """Fork an existing thread into a new persistent thread."""

    async def list_threads(self, *, limit: int = 100) -> list[BackendThread]:
        """List backend-visible thread references."""

    async def start_turn(self, request: TurnStartRequest) -> BackendTurn:
        """Start a bounded turn with explicit policy."""

    def stream_events(self, turn_id: str) -> AsyncIterator[CodexEvent]:
        """Stream normalized events for one active turn."""

    async def steer(self, turn_id: str, prompt: str) -> None:
        """Append guidance to an active turn."""

    async def interrupt(self, turn_id: str) -> None:
        """Interrupt an active turn."""

    async def read_thread(self, thread_id: str) -> Any:
        """Read persisted thread state without starting a turn."""

    async def close(self) -> None:
        """Release processes, pipes, and local resources."""


__all__ = ["CodexBackend"]
