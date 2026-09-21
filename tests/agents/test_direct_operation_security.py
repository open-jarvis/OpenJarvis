"""Security gates for agents that execute outside ToolUsingAgent."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openjarvis.agents.claude_code import ClaudeCodeAgent
from openjarvis.agents.hybrid.baseline_cloud import BaselineCloudAgent
from openjarvis.agents.hybrid.mini_swe_agent import MiniSWEAgent
from openjarvis.agents.opencode import OpenCodeAgent
from openjarvis.agents.openhands import OpenHandsAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.security.capabilities import CapabilityPolicy


class _RecordingLimiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def check(self, key: str):
        self.keys.append(key)
        return True, 0.0


@pytest.mark.parametrize(
    ("agent_cls", "agent_id", "operation"),
    [
        (ClaudeCodeAgent, "restricted-claude", "agent_run"),
        (OpenCodeAgent, "restricted-opencode", "agent_run"),
        (OpenHandsAgent, "restricted-openhands", "agent_run"),
        (MiniSWEAgent, "restricted-mini-swe", "hybrid_agent_run"),
    ],
)
def test_registered_execution_agents_fail_closed_before_side_effects(
    agent_cls, agent_id, operation
):
    policy = CapabilityPolicy(default_deny=True)
    limiter = _RecordingLimiter()
    bus = EventBus(record_history=True)
    agent = agent_cls(
        MagicMock(),
        "test-model",
        bus=bus,
        capability_policy=policy,
        rate_limiter=limiter,
        agent_id=agent_id,
    )
    paradigm = MagicMock(return_value=("should not run", {}))
    if isinstance(agent, MiniSWEAgent):
        agent._run_paradigm = paradigm

    result = agent.run("perform workspace changes")

    assert result.metadata["security_denied"] is True
    assert "code:execute" in result.content
    assert limiter.keys == [f"{agent_id}:{operation}"]
    paradigm.assert_not_called()
    denied = [
        event
        for event in bus.history
        if event.event_type == EventType.CAPABILITY_DENIED
    ]
    assert denied[-1].data["agent_id"] == agent_id


def test_mini_swe_explicit_grants_allow_registered_agent_run():
    policy = CapabilityPolicy(default_deny=True)
    for capability in ("code:execute", "file:read", "file:write"):
        policy.grant("allowed-mini-swe", capability)
    limiter = _RecordingLimiter()
    agent = MiniSWEAgent(
        MagicMock(),
        "test-model",
        capability_policy=policy,
        rate_limiter=limiter,
        agent_id="allowed-mini-swe",
    )
    agent._run_paradigm = MagicMock(return_value=("completed", {"turns": 1}))

    result = agent.run("perform workspace changes")

    assert result.content == "completed"
    agent._run_paradigm.assert_called_once()
    assert limiter.keys == ["allowed-mini-swe:hybrid_agent_run"]


def test_hybrid_tavily_path_requires_network_before_search():
    policy = CapabilityPolicy(default_deny=True)
    limiter = _RecordingLimiter()
    agent = BaselineCloudAgent(
        MagicMock(),
        "test-model",
        cfg={"search_backend": "tavily"},
        capability_policy=policy,
        rate_limiter=limiter,
        agent_id="restricted-hybrid",
    )
    agent._run_paradigm = MagicMock(return_value=("should not run", {}))

    result = agent.run("research current facts")

    assert "network:fetch" in result.content
    agent._run_paradigm.assert_not_called()
    assert limiter.keys == ["restricted-hybrid:hybrid_agent_run"]
