"""Tests for tools/_stubs.py — ToolSpec, BaseTool, ToolExecutor."""

from __future__ import annotations

import json

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.security.capabilities import DEFAULT_TOOL_CAPABILITIES
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec
from openjarvis.tools.code_interpreter import CodeInterpreterTool

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


class _ScalarBoundaryGuard:
    """Test guard that rewrites outbound arguments to a JSON scalar."""

    def check_outbound(self, tool_call: ToolCall) -> ToolCall:
        return ToolCall(
            id=tool_call.id,
            name=tool_call.name,
            arguments=json.dumps("redacted"),
        )


class _NamedTool(BaseTool):
    """Tool with caller-controlled metadata for capability-policy tests."""

    def __init__(self, name: str, required_capabilities=None) -> None:
        self.tool_id = name
        self._required_capabilities = required_capabilities or []
        self.calls = 0

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Capability test tool.",
            required_capabilities=self._required_capabilities,
        )

    def execute(self, **params) -> ToolResult:
        self.calls += 1
        return ToolResult(tool_name=self.tool_id, content="executed")


class _RecordingPolicy:
    def __init__(self, allowed=()) -> None:
        self.allowed = set(allowed)
        self.checks = []

    def check(self, agent_id, capability, resource="") -> bool:
        self.checks.append((agent_id, capability, resource))
        return capability in self.allowed


class _FalseyDenyAllPolicy(_RecordingPolicy):
    def __bool__(self) -> bool:
        return False


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
    def test_default_deny_blocks_code_interpreter_without_declared_capability(self):
        policy = _RecordingPolicy()
        tool = CodeInterpreterTool()
        assert tool.spec.required_capabilities == []
        executor = ToolExecutor([tool], capability_policy=policy, agent_id="deny-all")

        result = executor.execute(
            ToolCall(
                id="1",
                name="code_interpreter",
                arguments='{"code":"print(6 * 7)"}',
            )
        )

        assert result.success is False
        assert "Capability 'code:execute' denied" in result.content
        assert policy.checks == [("deny-all", "code:execute", "code_interpreter")]

    @pytest.mark.parametrize(
        ("tool_name", "canonical_capabilities"),
        list(DEFAULT_TOOL_CAPABILITIES.items()),
    )
    def test_every_canonical_tool_capability_is_enforced(
        self, tool_name, canonical_capabilities
    ):
        tool = _NamedTool(tool_name)
        policy = _RecordingPolicy()
        executor = ToolExecutor([tool], capability_policy=policy, agent_id="deny-all")

        result = executor.execute(ToolCall(id="1", name=tool_name, arguments="{}"))

        expected = canonical_capabilities[0].value
        assert result.success is False
        assert tool.calls == 0
        assert policy.checks == [("deny-all", expected, tool_name)]

    def test_declared_capability_cannot_replace_canonical_security_floor(self):
        tool = _NamedTool("code_interpreter", ["file:read"])
        policy = _RecordingPolicy(allowed={"file:read"})
        executor = ToolExecutor([tool], capability_policy=policy, agent_id="limited")

        result = executor.execute(
            ToolCall(id="1", name="code_interpreter", arguments="{}")
        )

        assert result.success is False
        assert tool.calls == 0
        assert policy.checks == [
            ("limited", "file:read", "code_interpreter"),
            ("limited", "code:execute", "code_interpreter"),
        ]

    def test_falsey_policy_object_cannot_bypass_enforcement(self):
        tool = _NamedTool("code_interpreter")
        policy = _FalseyDenyAllPolicy()
        executor = ToolExecutor([tool], capability_policy=policy, agent_id="deny-all")

        result = executor.execute(
            ToolCall(id="1", name="code_interpreter", arguments="{}")
        )

        assert result.success is False
        assert tool.calls == 0
        assert policy.checks == [("deny-all", "code:execute", "code_interpreter")]

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

    @pytest.mark.parametrize(
        ("arguments", "decoded_type"),
        [
            ("42", "int"),
            ("true", "bool"),
            ("null", "NoneType"),
            ("[]", "list"),
            ('"text"', "str"),
        ],
    )
    def test_execute_rejects_non_object_json(self, arguments, decoded_type):
        executor = ToolExecutor([_EchoTool()])
        call = ToolCall(id="1", name="echo", arguments=arguments)

        result = executor.execute(call)

        assert result.success is False
        assert result.content == (
            f"Invalid arguments: expected a JSON object, got {decoded_type}."
        )

    def test_execute_revalidates_boundary_guard_arguments(self):
        tool = _EchoTool()
        tool.is_local = False
        executor = ToolExecutor([tool], boundary_guard=_ScalarBoundaryGuard())
        call = ToolCall(id="1", name="echo", arguments='{"text":"safe"}')

        result = executor.execute(call)

        assert result.success is False
        assert result.content == ("Invalid arguments: expected a JSON object, got str.")

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

    def test_no_bus_works(self):
        executor = ToolExecutor([_EchoTool()])
        call = ToolCall(id="1", name="echo", arguments='{"text":"ok"}')
        result = executor.execute(call)
        assert result.success is True

    def test_empty_executor(self):
        executor = ToolExecutor([])
        assert executor.available_tools() == []
        assert executor.get_openai_tools() == []
