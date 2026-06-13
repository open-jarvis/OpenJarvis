"""Frontend ↔ Backend HTTP Integration Tests.

Validates the full HTTP request/response cycle between the React frontend
(InputArea.tsx) and the FastAPI backend (/v1/chat/completions).

- Payload shapes match the contract defined in test_api_contract.py
- Response JSON conforms to ChatCompletionResponse / ChatCompletionChunk
- SSE streaming chunks are parseable
- Error responses carry correct HTTP status codes
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402
from openjarvis.server.models import (  # noqa: E402
    ChatCompletionChunk,
    ChatCompletionResponse,
    UsageInfo,
)

from openjarvis.agents.bavaria_booking import BavariaBookingAgent  # noqa: E402
from openjarvis.agents.chief_of_staff import ChiefOfStaffAgent  # noqa: E402
from openjarvis.agents.legal_assistant import LegalAssistant  # noqa: E402
from openjarvis.agents.marketing_assistant import MarketingAssistant  # noqa: E402
from openjarvis.agents.operations_assistant import OperationsAssistant  # noqa: E402
from openjarvis.agents.security_assistant import SecurityAssistant  # noqa: E402
from openjarvis.agents._stubs import AgentResult  # noqa: E402
from openjarvis.core.registry import AgentRegistry  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_engine():
    """Return a mock engine that returns deterministic completions."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": "Backend says hello",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }

    async def mock_stream(messages, *, model, **kwargs):
        for token in ["Backend", " ", "says", " ", "hello"]:
            yield token

    engine.stream = mock_stream
    return engine


@pytest.fixture(autouse=True)
def _register_domain_agents():
    """Re-register domain agents after conftest clears the registry."""
    AgentRegistry.register_value("bavaria_booking", BavariaBookingAgent)
    AgentRegistry.register_value("chief_of_staff", ChiefOfStaffAgent)
    AgentRegistry.register_value("legal_assistant", LegalAssistant)
    AgentRegistry.register_value("marketing_assistant", MarketingAssistant)
    AgentRegistry.register_value("operations_assistant", OperationsAssistant)
    AgentRegistry.register_value("security_assistant", SecurityAssistant)


@pytest.fixture
def client():
    """FastAPI TestClient with a mocked inference engine."""
    engine = _make_mock_engine()
    app = create_app(engine, "test-model")
    return TestClient(app)


@pytest.fixture
def monkeypatch_agent_run(monkeypatch):
    """Replace all domain agent run() methods with a synchronous mock."""

    def _mock_run(self, input, context=None, **kwargs):
        return AgentResult(
            content=f"Mock response from {self.agent_id}",
            turns=1,
            metadata={"mock": True},
        )

    for aid in (
        "bavaria_booking",
        "chief_of_staff",
        "legal_assistant",
        "marketing_assistant",
        "operations_assistant",
        "security_assistant",
    ):
        cls = AgentRegistry.get(aid)
        monkeypatch.setattr(cls, "run", _mock_run)


# ---------------------------------------------------------------------------
# Non-streaming integration tests
# ---------------------------------------------------------------------------


class TestNonStreamingCompletion:
    """POST /v1/chat/completions with stream=False (default)."""

    def test_basic_payload_returns_200(self, client, monkeypatch_agent_run):
        """The simplest valid frontend payload must yield a 200 OK."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] is not None
        assert data["choices"][0]["finish_reason"] == "stop"

    def test_response_validates_against_chat_completion_response(self, client, monkeypatch_agent_run):
        """The response JSON must satisfy the Pydantic ChatCompletionResponse model."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "agent_id": "bavaria_booking",
            },
        )
        assert resp.status_code == 200
        parsed = ChatCompletionResponse.model_validate(resp.json())
        assert parsed.object == "chat.completion"
        assert len(parsed.choices) == 1
        assert parsed.choices[0].message.role == "assistant"
        assert parsed.choices[0].finish_reason == "stop"
        assert isinstance(parsed.usage, UsageInfo)
        assert parsed.usage.total_tokens >= 0

    def test_model_override_forwarded(self, client, monkeypatch_agent_run):
        """When the frontend sends a different model, the response must echo it."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["model"] == "gpt-4o"

    def test_agent_id_selects_domain_agent(self, client, monkeypatch_agent_run):
        """ agent_id in the payload must route to the matching domain agent."""
        for aid in (
            "bavaria_booking",
            "legal_assistant",
            "marketing_assistant",
            "operations_assistant",
            "security_assistant",
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "agent_id": aid,
                },
            )
            assert resp.status_code == 200, f"Failed for agent_id={aid}"
            content = resp.json()["choices"][0]["message"]["content"]
            assert f"Mock response from {aid}" in content

    def test_full_optional_fields_accepted(self, client, monkeypatch_agent_run):
        """InputArea.tsx sends temperature, max_tokens, stream, agent_id — all must be accepted."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Be helpful"},
                    {"role": "user", "content": "Hello"},
                ],
                "temperature": 0.3,
                "max_tokens": 512,
                "stream": False,
                "agent_id": "legal_assistant",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Mock response from legal_assistant"

    def test_missing_model_returns_422(self, client):
        """Pydantic must reject a payload without the required 'model' field."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 422
        assert "model" in resp.text.lower() or "field required" in resp.text.lower()

    def test_empty_messages_accepted(self, client, monkeypatch_agent_run):
        """An empty messages array is unusual but should not crash the server."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"

    def test_unknown_agent_id_returns_400(self, client):
        """An unregistered agent_id must yield 400 Bad Request."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "agent_id": "nonexistent",
            },
        )
        assert resp.status_code == 400

    def test_content_type_must_be_json(self, client):
        """FastAPI should reject plain text or form-encoded payloads."""
        resp = client.post(
            "/v1/chat/completions",
            data="not json",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 422

    def test_usage_metadata_present(self, client, monkeypatch_agent_run):
        """Every completion response must include usage metadata."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        usage = resp.json().get("usage", {})
        assert "prompt_tokens" in usage
        assert "completion_tokens" in usage
        assert "total_tokens" in usage


# ---------------------------------------------------------------------------
# Streaming integration tests
# ---------------------------------------------------------------------------


class TestStreamingCompletion:
    """POST /v1/chat/completions with stream=True — SSE parsing."""

    def test_streaming_returns_sse_chunks(self, client, monkeypatch_agent_run):
        """stream=True must return text/event-stream with parseable SSE lines."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # Parse SSE lines
        events = []
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                payload = line.removeprefix("data: ")
                if payload == "[DONE]":
                    events.append({"done": True})
                    continue
                events.append(json.loads(payload))

        assert len(events) > 0
        assert events[-1].get("done") is True or events[-1]["choices"][0].get("finish_reason") == "stop"

    def test_streaming_chunks_validate_model(self, client, monkeypatch_agent_run):
        """Every SSE data line (except [DONE]) must parse into ChatCompletionChunk."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
                "agent_id": "bavaria_booking",
            },
        )
        assert resp.status_code == 200

        for line in resp.text.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line.removeprefix("data: ")
            if payload == "[DONE]":
                continue
            chunk = ChatCompletionChunk.model_validate(json.loads(payload))
            assert chunk.object == "chat.completion.chunk"
            assert len(chunk.choices) == 1

    def test_streaming_with_agent_id(self, client, monkeypatch_agent_run):
        """Streaming must work when an explicit agent_id is provided."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
                "agent_id": "marketing_assistant",
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_streaming_response_contains_model_name(self, client, monkeypatch_agent_run):
        """Every SSE chunk must echo the model name from the request."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "custom-model-v2",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        for line in resp.text.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line.removeprefix("data: ")
            if payload == "[DONE]":
                continue
            parsed = json.loads(payload)
            assert parsed.get("model") == "custom-model-v2"


# ---------------------------------------------------------------------------
# Round-trip contract tests
# ---------------------------------------------------------------------------


class TestPayloadResponseRoundTrip:
    """Verify that the exact payload InputArea.tsx sends round-trips correctly."""

    def _frontend_payload(self, **overrides: Any) -> Dict[str, Any]:
        """Build a payload identical to InputArea.tsx:handleSend."""
        base = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello from frontend"}],
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 1024,
        }
        base.update(overrides)
        return base

    def test_frontend_non_streaming_roundtrip(self, client, monkeypatch_agent_run):
        """Exact InputArea.tsx non-streaming payload must return a valid ChatCompletionResponse."""
        payload = self._frontend_payload(stream=False, agent_id="bavaria_booking")
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "created" in data
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["role"] == "assistant"

    def test_frontend_streaming_roundtrip(self, client, monkeypatch_agent_run):
        """Exact InputArea.tsx streaming payload must return valid SSE chunks."""
        payload = self._frontend_payload(stream=True, agent_id=None)
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # Ensure at least one content-bearing chunk exists
        has_content = False
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                payload_text = line.removeprefix("data: ")
                if payload_text == "[DONE]":
                    continue
                parsed = json.loads(payload_text)
                delta = parsed["choices"][0]["delta"]
                if delta.get("content"):
                    has_content = True
        assert has_content
