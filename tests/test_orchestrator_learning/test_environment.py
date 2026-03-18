"""Tests for orchestrator RL environment."""

from __future__ import annotations

import pytest

from openjarvis.core.types import ToolResult
from openjarvis.learning.intelligence.orchestrator.environment import (
    OrchestratorEnvironment,
)
from openjarvis.learning.intelligence.orchestrator.types import OrchestratorAction
from openjarvis.tools._stubs import BaseTool, ToolSpec

# -- Mock tool ---------------------------------------------------------------


class _MockCalculator(BaseTool):
    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description="mock calculator",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "math expression",
                    },
                },
            },
        )

    def execute(self, **params) -> ToolResult:
        expr = params.get("expression", "")
        try:
            result = str(eval(expr))  # noqa: S307
        except Exception as e:
            return ToolResult(
                tool_name="calculator",
                content=f"Error: {e}",
                success=False,
            )
        return ToolResult(
            tool_name="calculator",
            content=result,
            success=True,
        )


# -- Tests -------------------------------------------------------------------


class TestOrchestratorEnvironment:
    def test_reset_creates_clean_state(self):
        env = OrchestratorEnvironment(tools=[_MockCalculator()])
        state = env.reset("What is 2+2?")
        assert state.initial_prompt == "What is 2+2?"
        assert state.num_turns() == 0
        assert state.final_answer is None

    def test_step_executes_tool(self):
        env = OrchestratorEnvironment(tools=[_MockCalculator()])
        state = env.reset("q")
        action = OrchestratorAction(
            thought="calc",
            tool_name="calculator",
            tool_input="2+2",
        )
        state, obs = env.step(state, action)
        assert state.num_turns() == 1
        assert obs.latency_seconds >= 0

    def test_is_done_on_final_answer(self):
        env = OrchestratorEnvironment(tools=[_MockCalculator()])
        state = env.reset("q")
        action = OrchestratorAction(
            thought="done",
            tool_name="calculator",
            tool_input="2+2",
            is_final_answer=True,
        )
        state, obs = env.step(state, action)
        assert env.is_done(state) is True

    def test_is_done_on_max_turns(self):
        env = OrchestratorEnvironment(tools=[_MockCalculator()], max_turns=2)
        state = env.reset("q")
        for _ in range(2):
            action = OrchestratorAction(
                thought="go", tool_name="calculator", tool_input="1+1"
            )
            state, obs = env.step(state, action)
        assert env.is_done(state) is True

    def test_invalid_tool_raises(self):
        env = OrchestratorEnvironment(tools=[_MockCalculator()])
        state = env.reset("q")
        action = OrchestratorAction(
            thought="t", tool_name="nonexistent", tool_input="x"
        )
        with pytest.raises(ValueError, match="not available"):
            env.step(state, action)

    def test_max_turns_exceeded_raises(self):
        env = OrchestratorEnvironment(tools=[_MockCalculator()], max_turns=1)
        state = env.reset("q")
        action = OrchestratorAction(
            thought="go", tool_name="calculator", tool_input="1+1"
        )
        state, _ = env.step(state, action)
        with pytest.raises(ValueError, match="exceeded"):
            env.step(state, action)

    def test_get_available_tools(self):
        env = OrchestratorEnvironment(tools=[_MockCalculator()])
        assert env.get_available_tools() == ["calculator"]

    def test_not_done_initially(self):
        env = OrchestratorEnvironment(tools=[_MockCalculator()])
        state = env.reset("q")
        assert env.is_done(state) is False
