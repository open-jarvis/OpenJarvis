"""Independent resource lanes for model and interactive task work."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from openjarvis.tasks.types import ExecutionLane

_T = TypeVar("_T")


class ExecutionLaneScheduler:
    """Bound concurrency independently for model and exclusive UI resources."""

    def __init__(
        self,
        *,
        model_concurrency: int = 4,
        interactive_concurrency: int = 1,
    ) -> None:
        if model_concurrency <= 0:
            raise ValueError("model_concurrency must be positive")
        if interactive_concurrency != 1:
            raise ValueError("interactive_lane must remain exclusive")
        self._limits = {
            ExecutionLane.MODEL: model_concurrency,
            ExecutionLane.INTERACTIVE: interactive_concurrency,
        }
        self._semaphores = {
            lane: asyncio.Semaphore(limit)
            for lane, limit in self._limits.items()
        }
        self._active = {
            ExecutionLane.MODEL: 0,
            ExecutionLane.INTERACTIVE: 0,
        }
        self._state_lock = asyncio.Lock()

    async def run(
        self,
        lane: ExecutionLane,
        operation: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Run one operation without consuming capacity from the other lane."""

        semaphore = self._semaphores[lane]
        async with semaphore:
            async with self._state_lock:
                self._active[lane] += 1
            try:
                return await operation()
            finally:
                async with self._state_lock:
                    self._active[lane] -= 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        """Return credential-free lane limits and active counts."""

        return {
            lane.value: {
                "limit": self._limits[lane],
                "active": self._active[lane],
            }
            for lane in ExecutionLane
        }


__all__ = ["ExecutionLaneScheduler"]
