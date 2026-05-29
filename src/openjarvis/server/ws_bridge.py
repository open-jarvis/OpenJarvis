"""WebSocket bridge: EventBus → connected WebSocket clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from openjarvis.core.events import Event, EventBus, EventType

try:
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover
    pass  # FastAPI is optional; create_ws_router will fail at call time

logger = logging.getLogger(__name__)

# Agent-related event types to forward
_AGENT_EVENTS = {
    EventType.AGENT_TICK_START,
    EventType.AGENT_TICK_END,
    EventType.AGENT_TICK_ERROR,
    EventType.AGENT_BUDGET_EXCEEDED,
    EventType.AGENT_STALL_DETECTED,
    EventType.AGENT_MESSAGE_RECEIVED,
    EventType.AGENT_CHECKPOINT_SAVED,
    EventType.TOOL_CALL_START,
    EventType.TOOL_CALL_END,
    EventType.INFERENCE_START,
    EventType.INFERENCE_END,
}


def create_ws_router(event_bus: EventBus) -> Any:
    """Create a FastAPI router with a WebSocket endpoint for agent events."""
    router = APIRouter()
    # Each connected client gets a queue + loop ref for thread-safe event delivery
    clients: dict[WebSocket, tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = {}

    def _on_event(event: Event) -> None:
        """Forward event to all connected WebSocket client queues (thread-safe)."""
        payload = {
            "type": event.event_type.value,
            "timestamp": event.timestamp,
            "data": event.data or {},
        }
        for ws, (queue, loop) in list(clients.items()):
            agent_filter = getattr(ws, "_agent_filter", None)
            # Tick events carry "agent_id"; tool-call events carry "agent".
            # Match either so a per-agent subscriber actually receives the
            # tool calls that make up its live trace (without this, only
            # tick_start/end pass the filter and the trace looks empty).
            data = event.data or {}
            event_agent = data.get("agent_id") or data.get("agent")
            if agent_filter and event_agent != agent_filter:
                continue
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except (RuntimeError, asyncio.QueueFull):
                pass  # Loop closed or client is slow

    # Subscribe to all agent events
    for event_type in _AGENT_EVENTS:
        event_bus.subscribe(event_type, _on_event)

    @router.websocket("/v1/agents/events")
    async def agent_events(websocket: WebSocket) -> None:
        from openjarvis.server.auth_middleware import websocket_authorized

        expected_key = getattr(websocket.app.state, "api_key", "")
        if not websocket_authorized(websocket, expected_key):
            # 1008 = policy violation; reject before accepting the connection.
            await websocket.close(code=1008)
            return
        await websocket.accept()
        # Parse agent_id filter from query string
        agent_id = websocket.query_params.get("agent_id")
        websocket._agent_filter = agent_id  # type: ignore[attr-defined]
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        loop = asyncio.get_running_loop()
        clients[websocket] = (queue, loop)
        try:
            while True:
                payload = await queue.get()
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            pass
        finally:
            clients.pop(websocket, None)

    return router


__all__ = ["create_ws_router"]
