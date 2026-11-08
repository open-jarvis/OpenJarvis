from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REGISTRY_PATH = "friday_ai.core.registry.AgentRegistry.get"


def test_run_ephemeral_creates_and_runs_agent():
    from friday_ai.agents.executor import AgentExecutor

    manager = MagicMock()
    executor = AgentExecutor(manager=manager, event_bus=MagicMock())

    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.run.return_value = MagicMock(content="Flushed.")
    mock_agent_cls.return_value = mock_agent_instance

    with patch(REGISTRY_PATH, return_value=mock_agent_cls):
        executor.run_ephemeral(
            agent_type="simple",
            system_prompt="Save important context.",
            input_text="Review and flush.",
        )
    assert mock_agent_instance.run.called


def test_run_ephemeral_passes_input():
    from friday_ai.agents.executor import AgentExecutor

    manager = MagicMock()
    executor = AgentExecutor(manager=manager, event_bus=MagicMock())

    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.run.return_value = MagicMock(content="Done.")
    mock_agent_cls.return_value = mock_agent_instance

    with patch(REGISTRY_PATH, return_value=mock_agent_cls):
        executor.run_ephemeral(
            agent_type="simple",
            system_prompt="Test prompt.",
            input_text="Hello world",
        )
    mock_agent_instance.run.assert_called_once_with("Hello world")


def test_run_ephemeral_resolves_tools_and_preserves_security():
    from friday_ai.agents.executor import AgentExecutor
    from friday_ai.agents.simple import SimpleAgent
    from friday_ai.core.events import EventBus
    from friday_ai.core.registry import AgentRegistry, ToolRegistry
    from friday_ai.core.types import ToolResult
    from friday_ai.security.capabilities import CapabilityPolicy
    from friday_ai.tools._stubs import BaseTool, ToolSpec

    class _FlushProbe(BaseTool):
        calls = 0

        @property
        def spec(self):
            return ToolSpec(
                name="flush_probe",
                description="persist session state",
                required_capabilities=["memory:write"],
            )

        def execute(self, **params):
            type(self).calls += 1
            return ToolResult(tool_name="flush_probe", content="stored")

    class _RecordingLimiter:
        def __init__(self):
            self.keys = []

        def check(self, key):
            self.keys.append(key)
            return True, 0.0

    engine = MagicMock()
    engine.generate.side_effect = [
        {
            "content": "",
            "tool_calls": [{"id": "flush", "name": "flush_probe", "arguments": "{}"}],
            "finish_reason": "tool_calls",
        },
        {"content": "done", "finish_reason": "stop"},
    ]
    policy = CapabilityPolicy(default_deny=True)
    policy.grant("_default", "memory:write")
    policy.deny("ephemeral:simple", "memory:write")
    limiter = _RecordingLimiter()
    system = SimpleNamespace(
        engine=engine,
        model="test-model",
        capability_policy=policy,
        rate_limiter=limiter,
    )
    AgentRegistry.register_value("simple", SimpleAgent)
    ToolRegistry.register_value("flush_probe", _FlushProbe)
    executor = AgentExecutor(
        manager=MagicMock(),
        event_bus=EventBus(record_history=True),
        system=system,
    )

    result = executor.run_ephemeral(
        agent_type="simple",
        system_prompt="persist",
        input_text="flush now",
        tools=["flush_probe"],
    )

    assert len(result.tool_results) == 1
    assert "memory:write" in result.tool_results[0].content
    assert _FlushProbe.calls == 0
    assert limiter.keys == ["ephemeral:simple:flush_probe"]
