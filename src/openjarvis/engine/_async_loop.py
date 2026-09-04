"""Run an asyncio event loop on a background thread.

``InferenceEngine.generate`` is synchronous, but some backends expose
async-only APIs — Apple's Foundation Models SDK is one. This bridges the two
without an ``asyncio.run`` per call, which would tear down and rebuild a loop
for every request and break SDKs holding loop-bound state.

Ported from IPW's ``ipw/clients/_async_loop.py``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any


class AsyncLoopRunner:
    """Own an event loop on a daemon thread and run coroutines against it."""

    def __init__(self, name: str = "openjarvis-async") -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name=name, daemon=True)
        self._thread.start()

    def run(self, coro: Any) -> Any:
        """Submit *coro* to the background loop and block for its result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def shutdown(self) -> None:
        if self._loop.is_closed():
            return

        async def _drain() -> None:
            current = asyncio.current_task()
            tasks = [
                task
                for task in asyncio.all_tasks()
                if task is not current and not task.done()
            ]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        try:
            asyncio.run_coroutine_threadsafe(_drain(), self._loop).result(timeout=5.0)
        except Exception:  # pragma: no cover - shutdown is best-effort
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)
        self._loop.close()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()


__all__ = ["AsyncLoopRunner"]
