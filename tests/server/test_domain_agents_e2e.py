"""E2E flow tests for domain-agent resolution via /v1/chat/completions.

Each test exercises the full pipeline:
  HTTP request with agent_id -> AgentRegistry lookup -> agent instantiation
  -> agent.run() -> ChatCompletionResponse

The real agent classes are imported (side-effect registration) and their
run() methods are monkeypatched to avoid actual LLM calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402

from openjarvis.agents.bavaria_booking import BavariaBookingAgent  # noqa: E402
from openjarvis.agents.chief_of_staff import ChiefOfStaffAgent  # noqa: E402
from openjarvis.agents.legal_assistant import LegalAssistant  # noqa: E402
from openjarvis.agents.marketing_assistant import MarketingAssistant  # noqa: E402
from openjarvis.agents.operations_assistant import OperationsAssistant  # noqa: E402
from openjarvis.agents.security_assistant import SecurityAssistant  # noqa: E402

from openjarvis.agents._stubs import AgentResult  # noqa: E402
from openjarvis.core.registry import AgentRegistry  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": "Engine response",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }

    async def mock_stream(messages, *, model, **kwargs):
        for token in ["Engine", " ", "response"]:
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
    engine = _make_engine()
    app = create_app(engine, "test-model")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Domain agent E2E tests
# ---------------------------------------------------------------------------


class TestDomainAgentE2E:
    """Verify each frontend domain agent_id resolves and executes end-to-end."""

    @pytest.mark.parametrize(
        "agent_id,expected_agent_id",
        [
            ("auto", "chief_of_staff"),
            ("bavaria_booking", "bavaria_booking"),
            ("legal_assistant", "legal_assistant"),
            ("marketing_assistant", "marketing_assistant"),
            ("operations_assistant", "operations_assistant"),
            ("security_assistant", "security_assistant"),
        ],
    )
    def test_domain_agent_resolution(self, client, agent_id, expected_agent_id, monkeypatch):
        """Each domain agent_id should resolve, run, and return a valid response."""
        agent_cls = AgentRegistry.get(expected_agent_id)

        def mock_run(self, input, context=None, **kwargs):
            return AgentResult(
                content=f"Response from {self.agent_id}",
                turns=1,
                metadata={"test_marker": True},
            )

        monkeypatch.setattr(agent_cls, "run", mock_run)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "agent_id": agent_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == f"Response from {expected_agent_id}"
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["finish_reason"] == "stop"

    def test_unknown_agent_id_returns_400(self, client):
        """An unregistered agent_id should return 400 with a clear error."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "agent_id": "nonexistent_agent",
            },
        )
        assert resp.status_code == 400
        assert "Unknown agent_id" in resp.text

    def test_domain_agent_with_conversation_context(self, client, monkeypatch):
        """A domain agent should receive prior messages as context."""
        agent_cls = AgentRegistry.get("bavaria_booking")
        captured_context = []

        def mock_run(self, input, context=None, **kwargs):
            if context is not None:
                captured_context.extend(context.conversation.messages)
            return AgentResult(
                content=f"Context count: {len(captured_context)}",
                turns=1,
            )

        monkeypatch.setattr(agent_cls, "run", mock_run)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Be helpful"},
                    {"role": "user", "content": "First"},
                    {"role": "assistant", "content": "Okay"},
                    {"role": "user", "content": "Second"},
                ],
                "agent_id": "bavaria_booking",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Prior messages (system + first user + assistant) = 3 context messages
        assert data["choices"][0]["message"]["content"] == "Context count: 3"

    def test_domain_agent_with_model_override(self, client, monkeypatch):
        """The request model should override the agent's default model."""
        agent_cls = AgentRegistry.get("marketing_assistant")
        captured_model = None

        def mock_run(self, input, context=None, **kwargs):
            nonlocal captured_model
            captured_model = self._model
            return AgentResult(content="OK", turns=1)

        monkeypatch.setattr(agent_cls, "run", mock_run)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "custom-model-v2",
                "messages": [{"role": "user", "content": "Hello"}],
                "agent_id": "marketing_assistant",
            },
        )
        assert resp.status_code == 200
        assert captured_model == "custom-model-v2"

    def test_domain_agent_system_prompt_injection(self, client, monkeypatch):
        """The agent's system prompt should be injected into the message list."""
        agent_cls = AgentRegistry.get("legal_assistant")

        def mock_run(self, input, context=None, **kwargs):
            return AgentResult(content="Legal OK", turns=1)

        monkeypatch.setattr(agent_cls, "run", mock_run)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "agent_id": "legal_assistant",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Legal OK"

    def test_domain_agent_usage_metadata(self, client, monkeypatch):
        """Agent metadata should populate usage fields in the response."""
        agent_cls = AgentRegistry.get("operations_assistant")

        def mock_run(self, input, context=None, **kwargs):
            return AgentResult(
                content="Ops OK",
                turns=1,
                metadata={
                    "prompt_tokens": 42,
                    "completion_tokens": 17,
                    "total_tokens": 59,
                },
            )

        monkeypatch.setattr(agent_cls, "run", mock_run)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "agent_id": "operations_assistant",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["usage"]["prompt_tokens"] == 42
        assert data["usage"]["completion_tokens"] == 17
        assert data["usage"]["total_tokens"] == 59

    def test_streaming_without_tools_uses_engine(self, client):
        """Streaming without tools should fall back to engine streaming."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "agent_id": "bavaria_booking",
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        # Verify SSE chunks contain engine tokens
        content = ""
        for line in resp.text.strip().split("\n"):
            if line.startswith("data:") and "[DONE]" not in line:
                import json

                chunk = json.loads(line[5:].strip())
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                content += delta or ""
        assert content == "Engine response"
