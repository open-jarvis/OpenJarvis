"""Tests for NativeReActAgent (formerly ReActAgent)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.native_react import NativeReActAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Conversation, Message, Role, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CalculatorStub(BaseTool):
    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description="Math calculator.",
            parameters={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        )

    def execute(self, **params) -> ToolResult:
        expr = params.get("expression", "0")
        try:
            val = eval(expr)  # noqa: S307
        except Exception as e:
            return ToolResult(tool_name="calculator", content=str(e), success=False)
        return ToolResult(tool_name="calculator", content=str(val), success=True)


class _ThinkStub(BaseTool):
    tool_id = "think"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="think",
            description="Thinking tool.",
            parameters={
                "type": "object",
                "properties": {"thought": {"type": "string"}},
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="think",
            content=params.get("thought", ""),
            success=True,
        )


def _engine_response(content, **extra):
    """Helper to build an engine response dict."""
    base = {
        "content": content,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": "test-model",
        "finish_reason": "stop",
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestNativeReActRegistration:
    def test_registration(self):
        AgentRegistry.register_value("native_react", NativeReActAgent)
        assert AgentRegistry.contains("native_react")

    def test_agent_id(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = NativeReActAgent(engine, "test-model")
        assert agent.agent_id == "native_react"

    def test_accepts_tools(self):
        assert NativeReActAgent.accepts_tools is True


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------


class TestNativeReActParsing:
    def _parser(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = NativeReActAgent(engine, "test-model")
        return agent._parse_response

    def test_parse_thought_action(self):
        parse = self._parser()
        text = (
            "Thought: I need to calculate 2+2.\n"
            "Action: calculator\n"
            'Action Input: {"expression": "2+2"}'
        )
        result = parse(text)
        assert result["thought"] == "I need to calculate 2+2."
        assert result["action"] == "calculator"
        assert "expression" in result["action_input"]
        assert result["final_answer"] == ""

    def test_parse_final_answer(self):
        parse = self._parser()
        text = "Thought: I know the answer.\nFinal Answer: 42"
        result = parse(text)
        assert result["thought"] == "I know the answer."
        assert result["final_answer"] == "42"
        assert result["action"] == ""

    def test_parse_no_structure(self):
        parse = self._parser()
        text = "Just a plain response with no structure."
        result = parse(text)
        assert result["thought"] == ""
        assert result["action"] == ""
        assert result["final_answer"] == ""

    def test_parse_multiline_thought(self):
        parse = self._parser()
        text = (
            "Thought: First I need to think.\n"
            "Then consider options.\n"
            "Final Answer: done"
        )
        result = parse(text)
        assert result["final_answer"] == "done"

    def test_parse_action_without_input(self):
        parse = self._parser()
        text = "Thought: Let me check.\nAction: calculator"
        result = parse(text)
        assert result["action"] == "calculator"
        assert result["action_input"] == ""

    def test_parse_case_insensitive_thought_action(self):
        parse = self._parser()
        text = (
            "thought: I need to calculate 2+2.\n"
            "action: calculator\n"
            'action input: {"expression": "2+2"}'
        )
        result = parse(text)
        assert result["thought"] == "I need to calculate 2+2."
        assert result["action"] == "calculator"
        assert "expression" in result["action_input"]

    def test_parse_case_insensitive_final_answer(self):
        parse = self._parser()
        text = "thought: I know the answer.\nfinal answer: 42"
        result = parse(text)
        assert result["final_answer"] == "42"


# ---------------------------------------------------------------------------
# Agent execution tests
# ---------------------------------------------------------------------------


class TestNativeReActAgent:
    def test_simple_no_tool_response(self):
        """Engine returns Final Answer on first call."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: Simple greeting.\nFinal Answer: Hello!"
        )
        bus = EventBus(record_history=True)
        agent = NativeReActAgent(engine, "test-model", bus=bus)
        result = agent.run("Hello")
        assert result.content == "Hello!"
        assert result.turns == 1
        assert result.tool_results == []

    def test_thought_action_observation(self):
        """Turn 1: action, Turn 2: final answer."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            _engine_response(
                "Thought: I need to calculate.\n"
                "Action: calculator\n"
                'Action Input: {"expression": "2+2"}'
            ),
            _engine_response("Thought: The result is 4.\nFinal Answer: 4"),
        ]
        bus = EventBus(record_history=True)
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            bus=bus,
        )
        result = agent.run("What is 2+2?")
        assert result.content == "4"
        assert result.turns == 2
        assert len(result.tool_results) == 1
        assert result.tool_results[0].tool_name == "calculator"
        assert result.tool_results[0].content == "4"

    def test_calculator_tool_use(self):
        """Verify calculator tool execution produces correct result."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            _engine_response(
                "Thought: Calculate.\nAction: calculator\n"
                'Action Input: {"expression": "3*7"}'
            ),
            _engine_response("Thought: Done.\nFinal Answer: 21"),
        ]
        agent = NativeReActAgent(engine, "test-model", tools=[_CalculatorStub()])
        result = agent.run("3 times 7")
        assert result.tool_results[0].content == "21"
        assert result.tool_results[0].success is True

    def test_multi_tool_turns(self):
        """Three tool calls before final answer."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            _engine_response(
                "Thought: Step 1.\nAction: calculator\n"
                'Action Input: {"expression": "1+1"}'
            ),
            _engine_response(
                "Thought: Step 2.\nAction: calculator\n"
                'Action Input: {"expression": "2+2"}'
            ),
            _engine_response(
                "Thought: Step 3.\nAction: think\n"
                'Action Input: {"thought": "combining results"}'
            ),
            _engine_response("Thought: All done.\nFinal Answer: Complete."),
        ]
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub(), _ThinkStub()],
        )
        result = agent.run("Multi step")
        assert result.turns == 4
        assert len(result.tool_results) == 3
        assert result.content == "Complete."

    def test_max_turns_exceeded(self):
        """Engine always returns actions -- hits max_turns."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: Keep going.\nAction: calculator\n"
            'Action Input: {"expression": "1+1"}'
        )
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            max_turns=3,
        )
        result = agent.run("Loop forever")
        assert result.turns == 3
        assert result.metadata.get("max_turns_exceeded") is True
        assert result.content == "Maximum turns reached without a final answer."

    def test_unknown_tool_error(self):
        """Action references nonexistent tool -- ToolResult with success=False."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            _engine_response(
                "Thought: Use a tool.\nAction: nonexistent\nAction Input: {}"
            ),
            _engine_response(
                "Thought: Error occurred.\nFinal Answer: Could not run tool."
            ),
        ]
        agent = NativeReActAgent(engine, "test-model", tools=[_CalculatorStub()])
        result = agent.run("Do something")
        assert len(result.tool_results) == 1
        assert result.tool_results[0].success is False
        assert "Unknown tool" in result.tool_results[0].content

    def test_event_bus_emissions(self):
        """Verify AGENT_TURN_START and AGENT_TURN_END events."""
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: Quick.\nFinal Answer: Done."
        )
        agent = NativeReActAgent(engine, "test-model", bus=bus)
        agent.run("Hello")
        event_types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in event_types
        assert EventType.AGENT_TURN_END in event_types

    def test_event_bus_tool_events(self):
        """Tool call should trigger TOOL_CALL_START and TOOL_CALL_END events."""
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            _engine_response(
                "Thought: Calc.\nAction: calculator\n"
                'Action Input: {"expression": "1+1"}'
            ),
            _engine_response("Thought: Done.\nFinal Answer: 2"),
        ]
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            bus=bus,
        )
        agent.run("Calc")
        event_types = [e.event_type for e in bus.history]
        assert EventType.TOOL_CALL_START in event_types
        assert EventType.TOOL_CALL_END in event_types

    def test_context_passing(self):
        """Pass AgentContext with conversation history."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: Simple.\nFinal Answer: Hi!"
        )
        conv = Conversation()
        conv.add(Message(role=Role.USER, content="Previous message"))
        conv.add(Message(role=Role.ASSISTANT, content="Previous response"))
        ctx = AgentContext(conversation=conv)
        agent = NativeReActAgent(engine, "test-model")
        agent.run("Hello", context=ctx)
        call_args = engine.generate.call_args
        messages = call_args[0][0]
        # System prompt + 2 context messages + user input
        assert len(messages) == 4
        assert messages[0].role == Role.SYSTEM
        assert messages[1].role == Role.USER
        assert messages[1].content == "Previous message"
        assert messages[3].role == Role.USER
        assert messages[3].content == "Hello"

    def test_with_think_tool(self):
        """Use think tool for internal reasoning."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            _engine_response(
                "Thought: Let me reason.\nAction: think\n"
                'Action Input: {"thought": "The user wants a greeting"}'
            ),
            _engine_response("Thought: Now I know.\nFinal Answer: Greetings!"),
        ]
        agent = NativeReActAgent(engine, "test-model", tools=[_ThinkStub()])
        result = agent.run("Say hi")
        assert result.content == "Greetings!"
        assert result.tool_results[0].tool_name == "think"
        assert result.tool_results[0].content == "The user wants a greeting"

    def test_no_bus_works(self):
        """Agent runs correctly without an event bus."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: Easy.\nFinal Answer: Works!"
        )
        agent = NativeReActAgent(engine, "test-model")
        result = agent.run("Hello")
        assert result.content == "Works!"

    def test_plain_response_no_structure(self):
        """If engine returns no ReAct structure, treat as final answer."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response("Just a plain answer.")
        agent = NativeReActAgent(engine, "test-model")
        result = agent.run("Hello")
        assert result.content == "Just a plain answer."
        assert result.turns == 1

    def test_observation_appended_to_messages(self):
        """Observation from tool result is sent back to the engine."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            _engine_response(
                "Thought: Calc.\nAction: calculator\n"
                'Action Input: {"expression": "5+5"}'
            ),
            _engine_response("Thought: Got it.\nFinal Answer: 10"),
        ]
        agent = NativeReActAgent(engine, "test-model", tools=[_CalculatorStub()])
        agent.run("What is 5+5?")
        # Check second call messages
        second_call = engine.generate.call_args_list[1]
        messages = second_call[0][0]
        # Last message should be the observation
        last_msg = messages[-1]
        assert last_msg.role == Role.USER
        assert "Observation:" in last_msg.content
        assert "10" in last_msg.content

    def test_system_prompt_includes_tool_names(self):
        """System prompt should list available tool names."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: Done.\nFinal Answer: ok"
        )
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub(), _ThinkStub()],
        )
        agent.run("Hello")
        call_args = engine.generate.call_args
        messages = call_args[0][0]
        system_msg = messages[0]
        assert "calculator" in system_msg.content
        assert "think" in system_msg.content

    def test_system_prompt_no_tools(self):
        """System prompt should say 'No tools available.' when no tools."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: No tools.\nFinal Answer: ok"
        )
        agent = NativeReActAgent(engine, "test-model")
        agent.run("Hello")
        call_args = engine.generate.call_args
        messages = call_args[0][0]
        assert "No tools available." in messages[0].content

    def test_max_turns_1(self):
        """With max_turns=1 and an action, should stop after 1 turn."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            'Thought: Go.\nAction: calculator\nAction Input: {"expression": "1"}'
        )
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            max_turns=1,
        )
        result = agent.run("Calc")
        assert result.turns == 1
        assert result.metadata.get("max_turns_exceeded") is True

    def test_event_data_agent_turn_start(self):
        """AGENT_TURN_START event data should include agent id and input."""
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: Quick.\nFinal Answer: Hi"
        )
        agent = NativeReActAgent(engine, "test-model", bus=bus)
        agent.run("test input")
        start_events = [
            e for e in bus.history if e.event_type == EventType.AGENT_TURN_START
        ]
        assert len(start_events) == 1
        assert start_events[0].data["agent"] == "native_react"
        assert start_events[0].data["input"] == "test input"

    def test_system_prompt_enriched_descriptions(self):
        """System prompt should include parameter schemas, not just names."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = _engine_response(
            "Thought: Done.\nFinal Answer: ok"
        )
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub(), _ThinkStub()],
        )
        agent.run("Hello")
        call_args = engine.generate.call_args
        messages = call_args[0][0]
        system_content = messages[0].content
        # Should contain tool name as header
        assert "### calculator" in system_content
        assert "### think" in system_content
        # Should contain parameter info
        assert "expression" in system_content
        assert "string" in system_content

    def test_case_insensitive_execution(self):
        """Agent handles lowercase action/thought/final answer from the LLM."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            _engine_response(
                "thought: I need to calculate.\n"
                "action: calculator\n"
                'action input: {"expression": "2+2"}'
            ),
            _engine_response("thought: The result is 4.\nfinal answer: 4"),
        ]
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        result = agent.run("What is 2+2?")
        assert result.content == "4"
        assert result.turns == 2


@pytest.mark.parametrize("model", ["qwen3:8b", "gpt-oss:120b"])
def test_native_react_with_different_models(model):
    """NativeReActAgent works with different model names."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = _engine_response(
        "Thought: Responding.\nFinal Answer: Hello!"
    )
    agent = NativeReActAgent(engine, model)
    result = agent.run("Hello")
    assert result.content == "Hello!"
    call_kwargs = engine.generate.call_args[1]
    assert call_kwargs["model"] == model
