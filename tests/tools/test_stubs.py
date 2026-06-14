"""Tests for tools/_stubs.py — ToolSpec, BaseTool, ToolExecutor."""

from __future__ import annotations

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _EchoTool(BaseTool):
    """Minimal tool that echoes its input."""

    tool_id = "echo"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="echo",
            description="Echoes input back.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            category="testing",
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="echo",
            content=params.get("text", ""),
            success=True,
        )


class _ErrorTool(BaseTool):
    """Tool that always raises."""

    tool_id = "error"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="error", description="Always errors.")

    def execute(self, **params) -> ToolResult:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# ToolSpec tests
# ---------------------------------------------------------------------------


class TestToolSpec:
    def test_defaults(self):
        s = ToolSpec(name="test", description="A test tool.")
        assert s.name == "test"
        assert s.description == "A test tool."
        assert s.parameters == {}
        assert s.category == ""
        assert s.cost_estimate == 0.0
        assert s.requires_confirmation is False

    def test_full_spec(self):
        s = ToolSpec(
            name="calc",
            description="Calculate things.",
            parameters={"type": "object"},
            category="math",
            cost_estimate=0.01,
            latency_estimate=0.5,
            requires_confirmation=True,
            metadata={"version": "1.0"},
        )
        assert s.category == "math"
        assert s.metadata["version"] == "1.0"


# ---------------------------------------------------------------------------
# BaseTool tests
# ---------------------------------------------------------------------------


class TestBaseTool:
    def test_echo_tool_spec(self):
        tool = _EchoTool()
        assert tool.spec.name == "echo"
        assert tool.tool_id == "echo"

    def test_echo_tool_execute(self):
        tool = _EchoTool()
        result = tool.execute(text="hello")
        assert result.content == "hello"
        assert result.success is True

    def test_to_openai_function(self):
        tool = _EchoTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "echo"
        assert fn["function"]["description"] == "Echoes input back."
        assert "properties" in fn["function"]["parameters"]


# ---------------------------------------------------------------------------
# ToolExecutor tests
# ---------------------------------------------------------------------------


class TestToolExecutor:
    def test_execute_success(self):
        executor = ToolExecutor([_EchoTool()])
        call = ToolCall(id="1", name="echo", arguments='{"text":"hi"}')
        result = executor.execute(call)
        assert result.success is True
        assert result.content == "hi"
        assert result.latency_seconds > 0

    def test_execute_unknown_tool(self):
        executor = ToolExecutor([_EchoTool()])
        call = ToolCall(id="1", name="nonexistent", arguments="{}")
        result = executor.execute(call)
        assert result.success is False
        assert "Unknown tool" in result.content

    def test_execute_invalid_json(self):
        executor = ToolExecutor([_EchoTool()])
        call = ToolCall(id="1", name="echo", arguments="not json")
        result = executor.execute(call)
        assert result.success is False
        assert "Invalid arguments JSON" in result.content

    def test_execute_empty_arguments(self):
        executor = ToolExecutor([_EchoTool()])
        call = ToolCall(id="1", name="echo", arguments="")
        result = executor.execute(call)
        assert result.success is True
        assert result.content == ""

    def test_execute_tool_error(self):
        executor = ToolExecutor([_ErrorTool()])
        call = ToolCall(id="1", name="error", arguments="{}")
        result = executor.execute(call)
        assert result.success is False
        assert "boom" in result.content

    def test_available_tools(self):
        executor = ToolExecutor([_EchoTool(), _ErrorTool()])
        specs = executor.available_tools()
        assert len(specs) == 2
        names = {s.name for s in specs}
        assert names == {"echo", "error"}

    def test_get_openai_tools(self):
        executor = ToolExecutor([_EchoTool()])
        tools = executor.get_openai_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "echo"

    def test_event_bus_integration(self):
        bus = EventBus(record_history=True)
        executor = ToolExecutor([_EchoTool()], bus=bus)
        call = ToolCall(id="1", name="echo", arguments='{"text":"ping"}')
        executor.execute(call)
        events = bus.history
        types = [e.event_type for e in events]
        assert EventType.TOOL_CALL_START in types
        assert EventType.TOOL_CALL_END in types
        # Check start event data
        start = [e for e in events if e.event_type == EventType.TOOL_CALL_START][0]
        assert start.data["tool"] == "echo"
        # Check end event data
        end = [e for e in events if e.event_type == EventType.TOOL_CALL_END][0]
        assert end.data["success"] is True

    def test_event_bus_on_error(self):
        bus = EventBus(record_history=True)
        executor = ToolExecutor([_ErrorTool()], bus=bus)
        call = ToolCall(id="1", name="error", arguments="{}")
        executor.execute(call)
        end = [e for e in bus.history if e.event_type == EventType.TOOL_CALL_END][0]
        assert end.data["success"] is False

    def test_event_bus_includes_agent_id(self):
        bus = EventBus(record_history=True)
        executor = ToolExecutor([_EchoTool()], bus=bus, agent_id="test-agent")
        call = ToolCall(id="1", name="echo", arguments='{"text":"ping"}')
        executor.execute(call)
        end = [e for e in bus.history if e.event_type == EventType.TOOL_CALL_END][0]
        assert end.data["agent_id"] == "test-agent"

    def test_no_bus_works(self):
        executor = ToolExecutor([_EchoTool()])
        call = ToolCall(id="1", name="echo", arguments='{"text":"ok"}')
        result = executor.execute(call)
        assert result.success is True

    def test_empty_executor(self):
        executor = ToolExecutor([])
        assert executor.available_tools() == []
        assert executor.get_openai_tools() == []
