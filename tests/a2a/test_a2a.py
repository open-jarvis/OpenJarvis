"""Tests for A2A protocol (Phase 16.1)."""

from __future__ import annotations

from openjarvis.a2a.protocol import (
    A2ARequest,
    A2AResponse,
    A2ATask,
    AgentCard,
    TaskState,
)
from openjarvis.a2a.server import A2AServer
from openjarvis.core.events import EventBus, EventType


class TestAgentCard:
    def test_create_card(self):
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:8000",
        )
        assert card.name == "TestAgent"

    def test_to_dict(self):
        card = AgentCard(name="TestAgent", capabilities=["text"])
        d = card.to_dict()
        assert d["name"] == "TestAgent"
        assert "text" in d["capabilities"]


class TestA2ATask:
    def test_initial_state(self):
        task = A2ATask(input_text="Hello")
        assert task.state == TaskState.SUBMITTED
        assert task.input_text == "Hello"

    def test_to_dict(self):
        task = A2ATask(input_text="Hello")
        d = task.to_dict()
        assert d["state"] == "submitted"
        assert d["input"] == "Hello"
        assert "id" in d


class TestA2ARequest:
    def test_create_request(self):
        req = A2ARequest(method="tasks/send", params={"input": "hello"})
        assert req.method == "tasks/send"

    def test_to_dict(self):
        req = A2ARequest(method="tasks/send")
        d = req.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["method"] == "tasks/send"

    def test_to_json(self):
        req = A2ARequest(method="tasks/get")
        j = req.to_json()
        assert "tasks/get" in j


class TestA2AResponse:
    def test_success_response(self):
        resp = A2AResponse(result={"output": "hello"}, request_id="1")
        d = resp.to_dict()
        assert d["result"]["output"] == "hello"
        assert d["id"] == "1"
        assert "error" not in d

    def test_error_response(self):
        resp = A2AResponse(
            error={"code": -32601, "message": "Not found"},
            request_id="2",
        )
        d = resp.to_dict()
        assert d["error"]["code"] == -32601

    def test_from_json(self):
        import json

        data = json.dumps({"jsonrpc": "2.0", "result": "ok", "id": "3"})
        resp = A2AResponse.from_json(data)
        assert resp.result == "ok"
        assert resp.request_id == "3"


class TestA2AServer:
    def test_task_send(self):
        card = AgentCard(name="Test")
        server = A2AServer(card, handler=lambda x: f"Echo: {x}")
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {"input": "Hello"},
                "id": "1",
            }
        )
        assert response["result"]["state"] == "completed"
        assert "Echo: Hello" in response["result"]["output"]

    def test_task_send_with_message_format(self):
        card = AgentCard(name="Test")
        server = A2AServer(card, handler=lambda x: f"Got: {x}")
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {"message": {"role": "user", "parts": [{"text": "Hi"}]}},
                "id": "1",
            }
        )
        assert response["result"]["state"] == "completed"
        assert "Got: Hi" in response["result"]["output"]

    def test_task_get(self):
        card = AgentCard(name="Test")
        server = A2AServer(card, handler=lambda x: x)
        # First send a task
        send_resp = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {"input": "test"},
                "id": "1",
            }
        )
        task_id = send_resp["result"]["id"]

        # Now get it
        get_resp = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/get",
                "params": {"id": task_id},
                "id": "2",
            }
        )
        assert get_resp["result"]["id"] == task_id

    def test_task_get_not_found(self):
        card = AgentCard(name="Test")
        server = A2AServer(card)
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/get",
                "params": {"id": "nonexistent"},
                "id": "1",
            }
        )
        assert "error" in response

    def test_task_cancel(self):
        card = AgentCard(name="Test")
        server = A2AServer(card, handler=lambda x: x)
        send_resp = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {"input": "test"},
                "id": "1",
            }
        )
        task_id = send_resp["result"]["id"]

        cancel_resp = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/cancel",
                "params": {"id": task_id},
                "id": "2",
            }
        )
        assert cancel_resp["result"]["state"] == "canceled"

    def test_unknown_method(self):
        card = AgentCard(name="Test")
        server = A2AServer(card)
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "unknown/method",
                "params": {},
                "id": "1",
            }
        )
        assert "error" in response
        assert response["error"]["code"] == -32601

    def test_events_emitted(self):
        bus = EventBus(record_history=True)
        card = AgentCard(name="Test")
        server = A2AServer(card, handler=lambda x: x, bus=bus)
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {"input": "test"},
                "id": "1",
            }
        )
        event_types = {e.event_type for e in bus.history}
        assert EventType.A2A_TASK_RECEIVED in event_types
        assert EventType.A2A_TASK_COMPLETED in event_types

    def test_handler_error(self):
        card = AgentCard(name="Test")

        def bad_handler(x):
            raise ValueError("boom")

        server = A2AServer(card, handler=bad_handler)
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {"input": "test"},
                "id": "1",
            }
        )
        assert response["result"]["state"] == "failed"
