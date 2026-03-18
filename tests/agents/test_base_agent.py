"""Tests for BaseAgent helpers and ToolUsingAgent."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    BaseAgent,
    ToolUsingAgent,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Conversation, Message, Role, ToolCall, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class _ConcreteAgent(BaseAgent):
    agent_id = "test_agent"

    def run(self, input, context=None, **kwargs):
        return AgentResult(content="test", turns=1)


class _ConcreteToolAgent(ToolUsingAgent):
    agent_id = "test_tool_agent"

    def run(self, input, context=None, **kwargs):
        return AgentResult(content="test", turns=1)


class _DummyTool(BaseTool):
    tool_id = "dummy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dummy",
            description="Dummy tool.",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name="dummy", content="ok", success=True)


class _ConfirmTool(BaseTool):
    tool_id = "confirm"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="confirm",
            description="Confirmation-required tool.",
            parameters={"type": "object", "properties": {}},
            requires_confirmation=True,
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name="confirm", content="confirmed", success=True)


# ---------------------------------------------------------------------------
# BaseAgent tests
# ---------------------------------------------------------------------------


class TestBaseAgentInit:
    def test_stores_engine_and_model(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "test-model")
        assert agent._engine is engine
        assert agent._model == "test-model"

    def test_default_params(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m")
        assert agent._temperature == 0.7
        assert agent._max_tokens == 1024
        assert agent._bus is None

    def test_custom_params(self):
        bus = EventBus()
        engine = MagicMock()
        agent = _ConcreteAgent(
            engine,
            "m",
            bus=bus,
            temperature=0.1,
            max_tokens=256,
        )
        assert agent._temperature == 0.1
        assert agent._max_tokens == 256
        assert agent._bus is bus


class TestAcceptsTools:
    def test_base_agent_no_tools(self):
        assert _ConcreteAgent.accepts_tools is False

    def test_tool_using_agent_accepts_tools(self):
        assert _ConcreteToolAgent.accepts_tools is True


class TestEmitTurnStart:
    def test_with_bus(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m", bus=bus)
        agent._emit_turn_start("hello")
        events = [e for e in bus.history if e.event_type == EventType.AGENT_TURN_START]
        assert len(events) == 1
        assert events[0].data["agent"] == "test_agent"
        assert events[0].data["input"] == "hello"

    def test_without_bus(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m")
        # Should not raise
        agent._emit_turn_start("hello")


class TestEmitTurnEnd:
    def test_with_bus(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m", bus=bus)
        agent._emit_turn_end(turns=3, custom="val")
        events = [e for e in bus.history if e.event_type == EventType.AGENT_TURN_END]
        assert len(events) == 1
        assert events[0].data["agent"] == "test_agent"
        assert events[0].data["turns"] == 3
        assert events[0].data["custom"] == "val"

    def test_without_bus(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m")
        agent._emit_turn_end(turns=1)


class TestBuildMessages:
    def test_basic(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m")
        messages = agent._build_messages("hello")
        assert len(messages) == 1
        assert messages[0].role == Role.USER
        assert messages[0].content == "hello"

    def test_with_system_prompt(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m")
        messages = agent._build_messages("hello", system_prompt="Be helpful.")
        assert len(messages) == 2
        assert messages[0].role == Role.SYSTEM
        assert messages[0].content == "Be helpful."
        assert messages[1].role == Role.USER

    def test_with_context(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m")
        conv = Conversation()
        conv.add(Message(role=Role.USER, content="prev"))
        conv.add(Message(role=Role.ASSISTANT, content="reply"))
        ctx = AgentContext(conversation=conv)
        messages = agent._build_messages("new", ctx)
        assert len(messages) == 3
        assert messages[0].content == "prev"
        assert messages[1].content == "reply"
        assert messages[2].content == "new"

    def test_with_system_prompt_and_context(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m")
        conv = Conversation()
        conv.add(Message(role=Role.USER, content="prev"))
        ctx = AgentContext(conversation=conv)
        messages = agent._build_messages(
            "new",
            ctx,
            system_prompt="System.",
        )
        assert len(messages) == 3
        assert messages[0].role == Role.SYSTEM
        assert messages[1].content == "prev"
        assert messages[2].content == "new"


class TestGenerate:
    def test_delegates_to_engine(self):
        engine = MagicMock()
        engine.generate.return_value = {"content": "hi"}
        agent = _ConcreteAgent(engine, "m", temperature=0.5, max_tokens=100)
        result = agent._generate([Message(role=Role.USER, content="hi")])
        assert result["content"] == "hi"
        engine.generate.assert_called_once()
        call_kwargs = engine.generate.call_args[1]
        assert call_kwargs["model"] == "m"
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 100

    def test_extra_kwargs(self):
        engine = MagicMock()
        engine.generate.return_value = {"content": "hi"}
        agent = _ConcreteAgent(engine, "m")
        agent._generate([Message(role=Role.USER, content="hi")], tools=["t"])
        call_kwargs = engine.generate.call_args[1]
        assert call_kwargs["tools"] == ["t"]


class TestMaxTurnsResult:
    def test_default_message(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m", bus=bus)
        tr = [ToolResult(tool_name="t", content="x", success=True)]
        result = agent._max_turns_result(tr, turns=5)
        assert result.metadata["max_turns_exceeded"] is True
        assert result.turns == 5
        assert "Maximum turns" in result.content
        assert result.tool_results == tr
        # Should also emit turn end
        events = [e for e in bus.history if e.event_type == EventType.AGENT_TURN_END]
        assert len(events) == 1
        assert events[0].data["max_turns_exceeded"] is True

    def test_custom_content(self):
        engine = MagicMock()
        agent = _ConcreteAgent(engine, "m")
        result = agent._max_turns_result([], turns=3, content="custom msg")
        assert result.content == "custom msg"


class TestStripThinkTags:
    def test_full_think_block(self):
        text = "<think>internal reasoning</think>Answer here."
        assert BaseAgent._strip_think_tags(text) == "Answer here."

    def test_bare_closing_tag(self):
        text = "some reasoning</think>Answer here."
        assert BaseAgent._strip_think_tags(text) == "Answer here."

    def test_no_tags(self):
        text = "Just normal text."
        assert BaseAgent._strip_think_tags(text) == "Just normal text."

    def test_multiline_think(self):
        text = "<think>\nline1\nline2\n</think>\nFinal."
        assert BaseAgent._strip_think_tags(text) == "Final."

    def test_empty_after_strip(self):
        text = "<think>all thinking</think>"
        assert BaseAgent._strip_think_tags(text) == ""


# ---------------------------------------------------------------------------
# ToolUsingAgent tests
# ---------------------------------------------------------------------------


class TestToolUsingAgent:
    def test_creates_executor(self):
        engine = MagicMock()
        agent = _ConcreteToolAgent(engine, "m", tools=[_DummyTool()])
        assert agent._executor is not None
        assert len(agent._tools) == 1

    def test_default_max_turns(self):
        engine = MagicMock()
        agent = _ConcreteToolAgent(engine, "m")
        assert agent._max_turns == 10

    def test_custom_max_turns(self):
        engine = MagicMock()
        agent = _ConcreteToolAgent(engine, "m", max_turns=5)
        assert agent._max_turns == 5

    def test_empty_tools(self):
        engine = MagicMock()
        agent = _ConcreteToolAgent(engine, "m")
        assert agent._tools == []

    def test_inherits_base_helpers(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        agent = _ConcreteToolAgent(engine, "m", bus=bus)
        agent._emit_turn_start("hi")
        events = [e for e in bus.history if e.event_type == EventType.AGENT_TURN_START]
        assert len(events) == 1

    def test_propagates_confirmation_settings_to_executor(self):
        engine = MagicMock()
        confirm = MagicMock(return_value=True)
        agent = _ConcreteToolAgent(
            engine,
            "m",
            tools=[_ConfirmTool()],
            interactive=True,
            confirm_callback=confirm,
        )

        result = agent._executor.execute(
            ToolCall(id="1", name="confirm", arguments="{}")
        )

        assert result.success is True
        confirm.assert_called_once()
