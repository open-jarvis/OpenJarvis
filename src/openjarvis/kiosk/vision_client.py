"""Async WebSocket client that connects to the Vision WS server and feeds
events into an asyncio.Queue consumed by the kiosk main loop.

Three event types from vision: person_present (distance in m), person_left,
scene_empty."""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

RECONNECT_DELAYS = (1, 2, 4, 8, 15, 30)  # seconds, caps at 30


class VisionClient:
    """Connects to vision WS server, pushes events into an asyncio.Queue.

    Use ``events`` property to get the queue consumed by the kiosk main loop.
    Call ``run()`` to start (persistent reconnect). Call ``stop()`` to shut down.
    """

    def __init__(self, url: str = "ws://127.0.0.1:9876"):
        self._url = url
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._running = False

    @property
    def events(self) -> asyncio.Queue:
        """The event queue consumed by the kiosk main loop."""
        return self._queue

    async def run(self) -> None:
        """Connect and stream events into the queue. Reconnects forever."""
        import websockets

        self._running = True
        delay_idx = 0
        while self._running:
            try:
                async with websockets.connect(
                    self._url, ping_interval=30, close_timeout=2
                ) as ws:
                    delay_idx = 0  # reset on successful connect
                    logger.info("VisionClient connected to %s", self._url)
                    async for raw in ws:
                        if not self._running:
                            break
                        event = json.loads(raw)
                        # Drop oldest if consumer is slow (should never happen)
                        if self._queue.full():
                            try:
                                self._queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        await self._queue.put(event)
            except Exception as exc:
                if not self._running:
                    break
                delay = RECONNECT_DELAYS[min(delay_idx, len(RECONNECT_DELAYS) - 1)]
                delay_idx += 1
                logger.warning(
                    "VisionClient disconnected: %s. Reconnecting in %ds...",
                    exc, delay,
                )
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Signal the client to stop (does not close the queue)."""
        self._running = False
