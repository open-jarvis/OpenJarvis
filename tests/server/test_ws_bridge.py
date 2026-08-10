"""Tests for WebSocket event bridge."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from openjarvis.core.events import EventBus, EventType

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def app(event_bus):
    from openjarvis.server.ws_bridge import create_ws_router

    app = FastAPI()
    router = create_ws_router(event_bus)
    app.include_router(router)
    return app


class TestWSBridge:
    def test_websocket_receives_events(self, app, event_bus):
        client = TestClient(app)
        with client.websocket_connect("/v1/agents/events") as ws:
            event_bus.publish(
                EventType.AGENT_TICK_START,
                {
                    "agent_id": "test-123",
                    "agent_name": "test",
                },
            )
            time.sleep(0.05)  # Let call_soon_threadsafe deliver to queue
            data = ws.receive_json()
            assert data["type"] == "agent_tick_start"
            assert data["data"]["agent_id"] == "test-123"

    def test_websocket_filters_by_agent_id(self, app, event_bus):
        client = TestClient(app)
        with client.websocket_connect("/v1/agents/events?agent_id=agent-A") as ws:
            # This event should NOT be received (different agent)
            event_bus.publish(EventType.AGENT_TICK_START, {"agent_id": "agent-B"})
            # This event SHOULD be received
            event_bus.publish(EventType.AGENT_TICK_START, {"agent_id": "agent-A"})
            time.sleep(0.05)  # Let call_soon_threadsafe deliver to queue
            data = ws.receive_json()
            assert data["data"]["agent_id"] == "agent-A"

    def test_client_disconnect_stops_handler(self, event_bus):
        async def exercise():
            from openjarvis.server.ws_bridge import create_ws_router

            class FakeWebSocket:
                app = SimpleNamespace(state=SimpleNamespace(api_key=""))
                query_params = {}
                headers = {}

                async def accept(self):
                    pass

                async def receive(self):
                    return {"type": "websocket.disconnect"}

            endpoint = create_ws_router(event_bus).routes[0].endpoint
            await asyncio.wait_for(endpoint(FakeWebSocket()), timeout=1)

        asyncio.run(exercise())

    def test_simultaneous_client_message_does_not_drop_event(self, event_bus):
        async def exercise():
            from openjarvis.server.ws_bridge import create_ws_router

            class FakeWebSocket:
                def __init__(self):
                    self.app = SimpleNamespace(state=SimpleNamespace(api_key=""))
                    self.query_params = {}
                    self.headers = {}
                    self.sent = []
                    self.receive_count = 0
                    self.disconnect = asyncio.Event()

                async def accept(self):
                    pass

                async def receive(self):
                    self.receive_count += 1
                    if self.receive_count == 1:
                        event_bus.publish(
                            EventType.AGENT_TICK_START, {"agent_id": "not-dropped"}
                        )
                        return {"type": "websocket.receive", "text": "client message"}
                    await self.disconnect.wait()
                    return {"type": "websocket.disconnect"}

                async def send_json(self, payload):
                    self.sent.append(payload)
                    self.disconnect.set()

            websocket = FakeWebSocket()
            endpoint = create_ws_router(event_bus).routes[0].endpoint

            await asyncio.wait_for(endpoint(websocket), timeout=1)

            assert websocket.sent[0]["data"]["agent_id"] == "not-dropped"

        asyncio.run(exercise())

    def test_cancelling_handler_cleans_up_child_tasks(self, event_bus):
        async def exercise():
            from openjarvis.server.ws_bridge import create_ws_router

            class FakeWebSocket:
                def __init__(self):
                    self.app = SimpleNamespace(state=SimpleNamespace(api_key=""))
                    self.query_params = {}
                    self.headers = {}
                    self.receiving = asyncio.Event()
                    self.receive_cancelled = asyncio.Event()

                async def accept(self):
                    pass

                async def receive(self):
                    self.receiving.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        self.receive_cancelled.set()

            websocket = FakeWebSocket()
            endpoint = create_ws_router(event_bus).routes[0].endpoint
            handler = asyncio.create_task(endpoint(websocket))
            await websocket.receiving.wait()

            handler.cancel()
            with pytest.raises(asyncio.CancelledError):
                await handler

            assert websocket.receive_cancelled.is_set()
            assert not [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()
            ]

        asyncio.run(exercise())
