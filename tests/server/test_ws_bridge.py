"""Tests for WebSocket event bridge."""

from __future__ import annotations

import time

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.tasks.service import TaskService
from openjarvis.tasks.store import TaskStore

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

    def test_task_stream_replays_persisted_timeline(self, event_bus, tmp_path):
        from openjarvis.server.ws_bridge import create_ws_router

        store = TaskStore(tmp_path / "tasks.db")
        service = TaskService(store, bus=event_bus)
        task = service.create(
            task_id="task-stream",
            session_id="session-stream",
            correlation_id="correlation-stream",
            description="read-only stream test",
            component="test",
            cause="test",
            idempotency_key="stream-create",
        )
        task_app = FastAPI()
        task_app.state.api_key = ""
        task_app.include_router(
            create_ws_router(event_bus, task_service=service)
        )
        try:
            client = TestClient(task_app)
            with client.websocket_connect(
                f"/v1/tasks/events?task_id={task.task_id}&after_sequence=0"
            ) as ws:
                data = ws.receive_json()
                assert data["type"] == "task_event"
                assert data["data"]["task_id"] == task.task_id
                assert data["data"]["sequence"] == 1
        finally:
            store.close()
