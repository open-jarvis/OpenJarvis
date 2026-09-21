"""Tests for orchestrator RL environment."""

from __future__ import annotations

import pytest

from openjarvis.core.events import EventBus, EventType
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


class _ProbeTool(BaseTool):
    tool_id = "probe"

    def __init__(self, name: str, capabilities: list[str]) -> None:
        self._name = name
        self._capabilities = capabilities
        self.executed = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description="learning security enforcement probe",
            required_capabilities=self._capabilities,
        )

    def execute(self, **params) -> ToolResult:
        self.executed = True
        return ToolResult(tool_name=self._name, content="executed", success=True)


class _DenyPolicy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def check(self, agent_id: str, capability: str, resource: str) -> bool:
        self.calls.append((agent_id, capability, resource))
        return False


class _RecordingLimiter:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.keys: list[str] = []

    def check(self, key: str) -> tuple[bool, float]:
        self.keys.append(key)
        return self.allowed, 1.0 if not self.allowed else 0.0


# -- Tests -------------------------------------------------------------------


class TestOrchestratorEnvironment:
    def test_admin_capability_is_fail_closed_and_auditable(self):
        tool = _ProbeTool("admin_probe", ["system:admin"])
        policy = _DenyPolicy()
        limiter = _RecordingLimiter()
        bus = EventBus(record_history=True)
        env = OrchestratorEnvironment(
            tools=[tool],
            bus=bus,
            capability_policy=policy,
            rate_limiter=limiter,
        )

        state = env.reset("probe")
        _, observation = env.step(
            state,
            OrchestratorAction(
                thought="probe",
                tool_name="admin_probe",
                tool_input="{}",
            ),
        )

        assert "system:admin" in observation.content
        assert tool.executed is False
        assert limiter.keys == ["learning:admin_probe"]
        assert policy.calls == [("learning", "system:admin", "admin_probe")]
        denied = [
            event
            for event in bus.history
            if event.event_type == EventType.CAPABILITY_DENIED
        ]
        assert len(denied) == 1
        assert denied[0].data["agent_id"] == "learning"

    def test_canonical_capability_cannot_be_removed_in_learning_path(self):
        tool = _ProbeTool("channel_send", [])
        policy = _DenyPolicy()
        env = OrchestratorEnvironment(tools=[tool], capability_policy=policy)

        state = env.reset("probe")
        _, observation = env.step(
            state,
            OrchestratorAction(
                thought="probe",
                tool_name="channel_send",
                tool_input="{}",
            ),
        )

        assert "channel:send" in observation.content
        assert tool.executed is False
        assert policy.calls == [("learning", "channel:send", "channel_send")]

    def test_rate_limit_is_fail_closed_before_learning_dispatch(self):
        tool = _ProbeTool("admin_probe", ["system:admin"])
        limiter = _RecordingLimiter(allowed=False)
        env = OrchestratorEnvironment(tools=[tool], rate_limiter=limiter)

        state = env.reset("probe")
        _, observation = env.step(
            state,
            OrchestratorAction(
                thought="probe",
                tool_name="admin_probe",
                tool_input="{}",
            ),
        )

        assert "Rate limit exceeded" in observation.content
        assert limiter.keys == ["learning:admin_probe"]
        assert tool.executed is False

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
