"""Provider-search security regressions across hybrid agents."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import openjarvis.agents.hybrid.conductor as conductor_module
import openjarvis.agents.hybrid.minions as minions_module
from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid.advisors import AdvisorsAgent
from openjarvis.agents.hybrid.conductor import ConductorAgent
from openjarvis.agents.hybrid.minions import MinionsAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.security.capabilities import CapabilityPolicy


class _Limiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def check(self, key: str):
        self.keys.append(key)
        return True, 0.0


def _policy(agent_id: str, *, network: bool = False) -> CapabilityPolicy:
    policy = CapabilityPolicy(default_deny=True)
    for capability in ("code:execute", "file:read", "file:write"):
        policy.grant(agent_id, capability)
    if network:
        policy.grant(agent_id, "network:fetch")
    return policy


@pytest.mark.parametrize(
    ("agent_cls", "agent_id"),
    [(AdvisorsAgent, "advisors-sec"), (ConductorAgent, "conductor-sec")],
)
def test_enabled_provider_search_is_required_before_hybrid_run(agent_cls, agent_id):
    limiter = _Limiter()
    agent = agent_cls(
        MagicMock(),
        "cloud-model",
        cfg={"web_search": {"enabled": True}},
        capability_policy=_policy(agent_id),
        rate_limiter=limiter,
        agent_id=agent_id,
    )
    agent._run_paradigm = MagicMock(return_value=("should not run", {}))

    result = agent.run("research")

    assert "network:fetch" in result.content
    agent._run_paradigm.assert_not_called()
    assert limiter.keys == [f"{agent_id}:hybrid_agent_run"]


def test_minions_legacy_prefetch_is_required_before_hybrid_run():
    limiter = _Limiter()
    agent = MinionsAgent(
        MagicMock(),
        "cloud-model",
        capability_policy=_policy("minions-sec"),
        rate_limiter=limiter,
        agent_id="minions-sec",
    )
    agent._run_paradigm = MagicMock(return_value=("should not run", {}))
    context = AgentContext(metadata={"task": {"question": "recent facts"}})

    result = agent.run("research", context)

    assert "network:fetch" in result.content
    agent._run_paradigm.assert_not_called()
    assert limiter.keys == ["minions-sec:hybrid_agent_run"]


def test_advisors_provider_denial_prevents_provider_search(monkeypatch):
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = AdvisorsAgent(
        MagicMock(),
        "cloud-model",
        cfg={"web_search": {"enabled": True}},
        bus=bus,
        capability_policy=_policy("advisors-sec"),
        rate_limiter=limiter,
        agent_id="advisors-sec",
    )
    provider_search = MagicMock()
    monkeypatch.setattr(agent, "_call_anthropic_agent", provider_search)

    result = agent._executor_search(
        user="research",
        system="system",
        max_tokens=100,
        ws_max_uses=2,
        max_turns=2,
    )

    assert "network:fetch" in result[0]
    provider_search.assert_not_called()
    assert limiter.keys == ["advisors-sec:advisors_provider_search"]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data["tool"] == "advisors_provider_search"
        for event in bus.history
    )


def test_advisors_provider_positive_grant_executes(monkeypatch):
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = AdvisorsAgent(
        MagicMock(),
        "cloud-model",
        cfg={"web_search": {"enabled": True}},
        bus=bus,
        capability_policy=_policy("advisors-sec", network=True),
        rate_limiter=limiter,
        agent_id="advisors-sec",
    )
    provider_search = MagicMock(return_value=("findings", 1, 2, 1, 1))
    monkeypatch.setattr(agent, "_call_anthropic_agent", provider_search)

    result = agent._executor_search(
        user="research",
        system="system",
        max_tokens=100,
        ws_max_uses=2,
        max_turns=2,
    )

    assert result[0] == "findings"
    provider_search.assert_called_once()
    assert limiter.keys == ["advisors-sec:advisors_provider_search"]


def test_conductor_provider_denial_prevents_worker_search(monkeypatch):
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = ConductorAgent(
        MagicMock(),
        "cloud-model",
        bus=bus,
        capability_policy=_policy("conductor-sec"),
        rate_limiter=limiter,
        agent_id="conductor-sec",
    )
    raw_worker = MagicMock()
    monkeypatch.setattr(conductor_module, "_call_worker", raw_worker)

    result = agent._call_worker_secured(
        {"name": "worker", "endpoint": "anthropic", "model": "cloud-model"},
        "research",
        {},
        web_search_tool={"type": "web_search"},
    )

    assert "network:fetch" in result[0]
    raw_worker.assert_not_called()
    assert limiter.keys == ["conductor-sec:conductor_provider_search"]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data["tool"] == "conductor_provider_search"
        for event in bus.history
    )


def test_conductor_provider_positive_grant_executes_worker(monkeypatch):
    limiter = _Limiter()
    agent = ConductorAgent(
        MagicMock(),
        "cloud-model",
        capability_policy=_policy("conductor-sec", network=True),
        rate_limiter=limiter,
        agent_id="conductor-sec",
    )
    expected = ("findings", 1, 2, False, 1, 0.0)
    raw_worker = MagicMock(return_value=expected)
    monkeypatch.setattr(conductor_module, "_call_worker", raw_worker)

    result = agent._call_worker_secured(
        {"name": "worker", "endpoint": "anthropic", "model": "cloud-model"},
        "research",
        {},
        web_search_tool={"type": "web_search"},
    )

    assert result == expected
    raw_worker.assert_called_once()
    assert limiter.keys == ["conductor-sec:conductor_provider_search"]


def test_minions_provider_denial_prevents_prefetch(monkeypatch):
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = MinionsAgent(
        MagicMock(),
        "cloud-model",
        bus=bus,
        capability_policy=_policy("minions-sec"),
        rate_limiter=limiter,
        agent_id="minions-sec",
    )
    raw_prefetch = MagicMock()
    monkeypatch.setattr(minions_module, "_prefetch_context", raw_prefetch)

    result = agent._prefetch_context_secured(
        "recent facts",
        max_uses=2,
        search_backend="provider",
        tavily_max_results=3,
    )

    assert "network:fetch" in result["error"]
    raw_prefetch.assert_not_called()
    assert limiter.keys == ["minions-sec:minions_provider_prefetch"]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data["tool"] == "minions_provider_prefetch"
        for event in bus.history
    )


def test_minions_provider_positive_grant_executes_prefetch(monkeypatch):
    limiter = _Limiter()
    agent = MinionsAgent(
        MagicMock(),
        "cloud-model",
        capability_policy=_policy("minions-sec", network=True),
        rate_limiter=limiter,
        agent_id="minions-sec",
    )
    expected = {"text": "findings", "tokens": 3, "cost_usd": 0.1, "n_searches": 1}
    raw_prefetch = MagicMock(return_value=expected)
    monkeypatch.setattr(minions_module, "_prefetch_context", raw_prefetch)

    result = agent._prefetch_context_secured(
        "recent facts",
        max_uses=2,
        search_backend="provider",
        tavily_max_results=3,
    )

    assert result == expected
    raw_prefetch.assert_called_once()
    assert limiter.keys == ["minions-sec:minions_provider_prefetch"]
