"""Tests for BavariaBookingAgent — domain-specialised orchestrator."""

from __future__ import annotations

import asyncio
import sys

import pytest

from tests.agents.fake_engine import FakeEngine


def _import_fresh_bavaria_booking():
    """Force re-import so @AgentRegistry.register runs after conftest clears registries."""
    sys.modules.pop("openjarvis.agents.bavaria_booking", None)
    import openjarvis.agents.bavaria_booking  # noqa: F401


def test_agent_registered():
    """bavaria_booking must be discoverable in AgentRegistry."""
    _import_fresh_bavaria_booking()
    from openjarvis.core.registry import AgentRegistry

    assert AgentRegistry.contains("bavaria_booking")
    agent_cls = AgentRegistry.get("bavaria_booking")
    assert agent_cls is not None
    assert getattr(agent_cls, "agent_id", None) == "bavaria_booking"


def test_inherits_orchestrator():
    """BavariaBookingAgent must be a subclass of OrchestratorAgent."""
    _import_fresh_bavaria_booking()
    from openjarvis.agents.bavaria_booking import BavariaBookingAgent
    from openjarvis.agents.orchestrator import OrchestratorAgent

    assert issubclass(BavariaBookingAgent, OrchestratorAgent)


def test_default_system_prompt():
    """Default system prompt must embed domain keywords from the skill."""
    _import_fresh_bavaria_booking()
    from openjarvis.agents.bavaria_booking import BavariaBookingAgent

    engine = FakeEngine([{"content": "Final Answer: done"}])
    agent = BavariaBookingAgent(engine, "fake-model")
    prompt = agent._system_prompt

    assert prompt is not None
    assert "Landhaus Bavaria" in prompt
    assert "landhausbavaria.de" in prompt
    assert "Deskline" in prompt
    assert "Vercel" in prompt
    assert "React" in prompt
    assert "TailwindCSS" in prompt
    assert "OWASP" in prompt


def test_custom_system_prompt_override():
    """An explicitly passed system_prompt must override the domain default."""
    _import_fresh_bavaria_booking()
    from openjarvis.agents.bavaria_booking import BavariaBookingAgent

    custom = "You are a generic assistant."
    engine = FakeEngine([{"content": "Final Answer: ok"}])
    agent = BavariaBookingAgent(engine, "fake-model", system_prompt=custom)

    assert agent._system_prompt == custom
    assert "Landhaus Bavaria" not in agent._system_prompt


def test_run_with_mock_engine():
    """Agent must complete a single-turn run with a fake engine."""
    _import_fresh_bavaria_booking()
    from openjarvis.agents.bavaria_booking import BavariaBookingAgent
    from openjarvis.agents._stubs import AgentContext

    engine = FakeEngine([{"content": "The booking button uses the Deskline API."}])
    agent = BavariaBookingAgent(engine, "fake-model")

    ctx = AgentContext()
    result = asyncio.run(agent.run("How does the booking button work?", context=ctx))

    assert result.content is not None
    assert "Deskline" in result.content or "booking" in result.content.lower()
    assert result.turns == 1


def test_run_with_tool_call_and_observation():
    """Agent must execute a tool call requested by the engine and loop."""
    _import_fresh_bavaria_booking()
    from openjarvis.agents.bavaria_booking import BavariaBookingAgent
    from openjarvis.agents._stubs import AgentContext
    from openjarvis.tools._stubs import ToolSpec
    from openjarvis.core.types import ToolResult

    from openjarvis.tools._stubs import BaseTool

    class _EchoTool(BaseTool):
        tool_id = "echo"
        is_local = True
        _spec = ToolSpec(
            name="echo",
            description="Echo",
            parameters={"type": "object", "properties": {}},
        )

        @property
        def spec(self):
            return self._spec

        def execute(self, **params):
            return ToolResult(tool_name="echo", content="echo-response", success=True)

    echo_tool = _EchoTool()

    responses = [
        {
            "content": "I'll check that.",
            "tool_calls": [
                {"id": "call_1", "name": "echo", "arguments": "{}"},
            ],
        },
        {"content": "The booking flow is working correctly."},
    ]
    engine = FakeEngine(responses)
    agent = BavariaBookingAgent(engine, "fake-model", tools=[echo_tool])

    ctx = AgentContext()
    result = asyncio.run(agent.run("Check booking flow", context=ctx))

    assert result.content is not None
    assert result.turns == 2
    assert len(result.tool_results) == 1
    assert result.tool_results[0].tool_name == "echo"
    assert result.tool_results[0].content == "echo-response"


def test_agent_id_constant():
    """agent_id class attribute must be 'bavaria_booking'."""
    _import_fresh_bavaria_booking()
    from openjarvis.agents.bavaria_booking import BavariaBookingAgent

    assert BavariaBookingAgent.agent_id == "bavaria_booking"
