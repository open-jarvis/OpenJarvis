"""Tests for tool execution timeout (Phase 14.1)."""

from __future__ import annotations

import time

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class SlowTool(BaseTool):
    """A tool that sleeps for a configurable duration."""

    tool_id = "slow_tool"

    def __init__(self, delay: float = 5.0):
        self._delay = delay

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="slow_tool",
            description="A tool that takes a long time.",
            timeout_seconds=1.0,  # 1-second timeout
        )

    def execute(self, **params) -> ToolResult:
        time.sleep(self._delay)
        return ToolResult(tool_name="slow_tool", content="Done", success=True)


class FastTool(BaseTool):
    """A tool that returns immediately."""

    tool_id = "fast_tool"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="fast_tool",
            description="A fast tool.",
            timeout_seconds=10.0,
            parameters={
                "type": "object",
                "properties": {"input": {"type": "string"}},
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="fast_tool",
            content=f"Result: {params.get('input', '')}",
            success=True,
        )


class TestToolTimeout:
    def test_fast_tool_succeeds(self):
        executor = ToolExecutor([FastTool()])
        call = ToolCall(id="1", name="fast_tool", arguments='{"input": "hello"}')
        result = executor.execute(call)
        assert result.success
        assert "hello" in result.content

    def test_slow_tool_times_out(self):
        executor = ToolExecutor([SlowTool(delay=5.0)])
        call = ToolCall(id="1", name="slow_tool", arguments="{}")
        result = executor.execute(call)
        assert not result.success
        assert "timed out" in result.content

    def test_timeout_event_emitted(self):
        bus = EventBus(record_history=True)
        executor = ToolExecutor([SlowTool(delay=5.0)], bus=bus)
        call = ToolCall(id="1", name="slow_tool", arguments="{}")
        executor.execute(call)

        timeout_events = [
            e for e in bus.history if e.event_type == EventType.TOOL_TIMEOUT
        ]
        assert len(timeout_events) == 1
        assert timeout_events[0].data["tool"] == "slow_tool"

    def test_default_timeout_used(self):
        """When ToolSpec has no timeout, the executor default is used."""

        class NoTimeoutTool(BaseTool):
            tool_id = "no_timeout"

            @property
            def spec(self):
                return ToolSpec(
                    name="no_timeout",
                    description="test",
                    timeout_seconds=0,
                )

            def execute(self, **params):
                return ToolResult(tool_name="no_timeout", content="ok")

        executor = ToolExecutor([NoTimeoutTool()], default_timeout=60.0)
        call = ToolCall(id="1", name="no_timeout", arguments="{}")
        result = executor.execute(call)
        assert result.success

    def test_timeout_seconds_on_toolspec(self):
        spec = ToolSpec(name="test", description="test", timeout_seconds=42.0)
        assert spec.timeout_seconds == 42.0

    def test_unknown_tool(self):
        executor = ToolExecutor([FastTool()])
        call = ToolCall(id="1", name="nonexistent", arguments="{}")
        result = executor.execute(call)
        assert not result.success
        assert "Unknown tool" in result.content
