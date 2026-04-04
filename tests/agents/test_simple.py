"""Tests for the SimpleAgent."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents._stubs import AgentContext, AgentResult
from openjarvis.agents.simple import SimpleAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Conversation, Message, Role


def _make_mock_engine(content: str = "Hello there!") -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


class TestSimpleAgent:
    def test_basic_run(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model")
        result = agent.run("Hello")
        assert isinstance(result, AgentResult)
        assert result.content == "Hello there!"
        assert result.turns == 1
        engine.generate.assert_called_once()

    def test_agent_id(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model")
        assert agent.agent_id == "simple"

    def test_with_context_conversation(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model")
        conv = Conversation()
        conv.add(Message(role=Role.SYSTEM, content="You are helpful."))
        ctx = AgentContext(conversation=conv)
        agent.run("Hello", context=ctx)
        call_args = engine.generate.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        # Should have system message + user message
        assert len(messages) == 2
        assert messages[0].role == Role.SYSTEM
        assert messages[1].role == Role.USER

    def test_without_context(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model")
        agent.run("Hello")
        call_args = engine.generate.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        # Default system prompt + user message
        assert len(messages) == 2
        assert messages[0].role == Role.SYSTEM
        assert messages[1].role == Role.USER

    def test_custom_temperature(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model", temperature=0.1)
        agent.run("Hello")
        call_kwargs = engine.generate.call_args[1]
        assert call_kwargs["temperature"] == 0.1

    def test_custom_max_tokens(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model", max_tokens=256)
        agent.run("Hello")
        call_kwargs = engine.generate.call_args[1]
        assert call_kwargs["max_tokens"] == 256

    def test_event_bus_integration(self):
        bus = EventBus(record_history=True)
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model", bus=bus)
        agent.run("Hello")
        event_types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in event_types
        assert EventType.AGENT_TURN_END in event_types
        # INFERENCE_START/END are now published by InstrumentedEngine,
        # not by agents directly

    def test_turn_start_event_data(self):
        bus = EventBus(record_history=True)
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model", bus=bus)
        agent.run("test input")
        evts = bus.history
        start = [e for e in evts if e.event_type == EventType.AGENT_TURN_START][0]
        assert start.data["agent"] == "simple"
        assert start.data["input"] == "test input"

    def test_turn_end_event_data(self):
        bus = EventBus(record_history=True)
        engine = _make_mock_engine("response text")
        agent = SimpleAgent(engine, "test-model", bus=bus)
        agent.run("Hello")
        end = [e for e in bus.history if e.event_type == EventType.AGENT_TURN_END][0]
        assert end.data["agent"] == "simple"
        assert end.data["content_length"] == len("response text")

    def test_no_bus_works(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model")
        result = agent.run("Hello")
        assert result.content == "Hello there!"

    def test_empty_content_response(self):
        engine = _make_mock_engine("")
        agent = SimpleAgent(engine, "test-model")
        result = agent.run("Hello")
        assert result.content == ""
        assert result.turns == 1

    def test_empty_context(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model")
        ctx = AgentContext()
        result = agent.run("Hello", context=ctx)
        assert result.content == "Hello there!"

    def test_result_has_no_tool_results(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "test-model")
        result = agent.run("Hello")
        assert result.tool_results == []

    def test_model_passthrough(self):
        engine = _make_mock_engine()
        agent = SimpleAgent(engine, "qwen3:8b")
        agent.run("Hello")
        call_kwargs = engine.generate.call_args[1]
        assert call_kwargs["model"] == "qwen3:8b"
