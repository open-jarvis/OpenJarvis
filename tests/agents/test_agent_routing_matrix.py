"""Cross-product tests: agent x engine x model."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.native_openhands import NativeOpenHandsAgent
from openjarvis.agents.native_react import NativeReActAgent
from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.agents.simple import SimpleAgent
from openjarvis.core.events import EventBus, EventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_engine(response="Hello!"):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": response,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


# ReAct needs a structured response to produce a result on first turn
_REACT_RESPONSE = "Thought: Simple query.\nFinal Answer: Hello!"
_OPENHANDS_RESPONSE = "Hello!"
_SIMPLE_RESPONSE = "Hello!"
_ORCHESTRATOR_RESPONSE = "Hello!"


AGENT_FACTORIES = {
    "simple": lambda e, m, bus: SimpleAgent(e, m, bus=bus),
    "orchestrator": lambda e, m, bus: OrchestratorAgent(e, m, bus=bus),
    "native_react": lambda e, m, bus: NativeReActAgent(e, m, bus=bus),
    "native_openhands": lambda e, m, bus: NativeOpenHandsAgent(e, m, bus=bus),
}

AGENT_RESPONSES = {
    "simple": _SIMPLE_RESPONSE,
    "orchestrator": _ORCHESTRATOR_RESPONSE,
    "native_react": _REACT_RESPONSE,
    "native_openhands": _OPENHANDS_RESPONSE,
}


# ---------------------------------------------------------------------------
# Common agent tests (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_key", ["simple", "orchestrator", "native_react", "native_openhands"])
class TestAgentCommon:
    def test_runs_with_mock_engine(self, agent_key):
        """Each agent type can run with a mock engine."""
        engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
        bus = EventBus(record_history=True)
        agent = AGENT_FACTORIES[agent_key](engine, "test-model", bus)
        result = agent.run("Hello")
        assert isinstance(result, AgentResult)

    def test_returns_valid_result(self, agent_key):
        """Result has correct structure."""
        engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
        bus = EventBus(record_history=True)
        agent = AGENT_FACTORIES[agent_key](engine, "test-model", bus)
        result = agent.run("Hello")
        assert hasattr(result, "content")
        assert hasattr(result, "turns")
        assert hasattr(result, "tool_results")
        assert hasattr(result, "metadata")

    def test_returns_nonempty_content(self, agent_key):
        """Result has non-empty content."""
        engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
        bus = EventBus(record_history=True)
        agent = AGENT_FACTORIES[agent_key](engine, "test-model", bus)
        result = agent.run("Hello")
        assert result.content != ""

    def test_emits_events(self, agent_key):
        """Each agent emits at least AGENT_TURN_START and inference events."""
        engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
        bus = EventBus(record_history=True)
        agent = AGENT_FACTORIES[agent_key](engine, "test-model", bus)
        agent.run("Hello")
        event_types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in event_types

    def test_handles_empty_input(self, agent_key):
        """Agent handles empty string input without crashing."""
        engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
        bus = EventBus(record_history=True)
        agent = AGENT_FACTORIES[agent_key](engine, "test-model", bus)
        result = agent.run("")
        assert isinstance(result, AgentResult)


# ---------------------------------------------------------------------------
# Agent identity tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent_key,expected_id",
    [
        ("simple", "simple"),
        ("orchestrator", "orchestrator"),
        ("native_react", "native_react"),
        ("native_openhands", "native_openhands"),
    ],
)
def test_agent_id(agent_key, expected_id):
    engine = _make_mock_engine()
    agent = AGENT_FACTORIES[agent_key](engine, "test-model", None)
    assert agent.agent_id == expected_id


# ---------------------------------------------------------------------------
# Model parametrization tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_key", ["simple", "orchestrator", "native_react", "native_openhands"])
@pytest.mark.parametrize("model", ["qwen3:8b", "llama3:70b", "gpt-oss:120b"])
def test_model_passthrough(agent_key, model):
    """Each agent passes the model name through to the engine."""
    engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
    agent = AGENT_FACTORIES[agent_key](engine, model, None)
    agent.run("Hello")
    call_kwargs = engine.generate.call_args[1]
    assert call_kwargs["model"] == model


# ---------------------------------------------------------------------------
# No-bus tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_key", ["simple", "orchestrator", "native_react", "native_openhands"])
def test_no_bus(agent_key):
    """All agents work without an event bus."""
    engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
    agent = AGENT_FACTORIES[agent_key](engine, "test-model", None)
    result = agent.run("Hello")
    assert isinstance(result, AgentResult)
    assert result.content != ""


# ---------------------------------------------------------------------------
# Turns tracking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_key", ["simple", "orchestrator", "native_react", "native_openhands"])
def test_single_turn_count(agent_key):
    """All agents report at least 1 turn for a simple query."""
    engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
    agent = AGENT_FACTORIES[agent_key](engine, "test-model", None)
    result = agent.run("Hello")
    assert result.turns >= 1


# ---------------------------------------------------------------------------
# Tool results are empty for no-tool queries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_key", ["simple", "orchestrator", "native_react", "native_openhands"])
def test_no_tool_results_for_simple_query(agent_key):
    """When no tools are used, tool_results should be empty."""
    engine = _make_mock_engine(AGENT_RESPONSES[agent_key])
    agent = AGENT_FACTORIES[agent_key](engine, "test-model", None)
    result = agent.run("Hello")
    assert result.tool_results == []
