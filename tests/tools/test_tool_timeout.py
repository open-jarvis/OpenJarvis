"""Tests for tool execution timeout (Phase 14.1)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

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

    def test_slow_tool_times_out_promptly(self):
        """execute() must return around the configured timeout, not wait
        for the slow tool to actually finish (issue #749)."""
        executor = ToolExecutor([SlowTool(delay=8.0)])
        call = ToolCall(id="1", name="slow_tool", arguments="{}")

        t0 = time.time()
        result = executor.execute(call)
        elapsed = time.time() - t0

        assert not result.success
        assert elapsed < 3.0, (
            f"execute() took {elapsed:.1f}s to return; expected it to "
            "return promptly after the 1s timeout instead of blocking "
            "until the 8s tool finished"
        )

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

    def test_repeated_timeouts_use_bounded_workers(self):
        """Timed-out calls must not create one live thread per invocation."""

        class BrieflyStuckTool(SlowTool):
            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="slow_tool",
                    description="test",
                    timeout_seconds=0.01,
                )

        executor = ToolExecutor([BrieflyStuckTool(delay=0.3)])
        results = [
            executor.execute(ToolCall(id=str(i), name="slow_tool", arguments="{}"))
            for i in range(24)
        ]

        workers = [
            thread
            for thread in threading.enumerate()
            if thread.name.startswith("openjarvis-tool-")
        ]
        assert len(workers) <= 8
        assert all(not result.success for result in results)
        assert any("capacity is exhausted" in result.content for result in results)

    def test_timed_out_tool_does_not_delay_process_exit(self):
        """A permanently blocked tool runs only on daemon workers."""
        source_root = Path(__file__).resolve().parents[2] / "src"
        env = {**os.environ, "PYTHONPATH": str(source_root)}
        script = """
import threading
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec

block = threading.Event()
class BlockingTool(BaseTool):
    tool_id = "blocking"
    @property
    def spec(self):
        return ToolSpec(name="blocking", description="test", timeout_seconds=0.01)
    def execute(self, **params):
        block.wait()
        return ToolResult(tool_name="blocking", content="done")

result = ToolExecutor([BlockingTool()]).execute(
    ToolCall(id="1", name="blocking", arguments="{}")
)
assert not result.success
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
