"""Security regressions for SkillOrchestra direct QA operations."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents.hybrid.skillorchestra.agent import SkillOrchestraAgent
from openjarvis.agents.hybrid.skillorchestra.pool import ModelSpec
from openjarvis.agents.hybrid.skillorchestra.tools import run_code, run_search
from openjarvis.core.events import EventBus, EventType
from openjarvis.security.capabilities import CapabilityPolicy


class _Limiter:
    def __init__(self, denied_key: str = "") -> None:
        self.denied_key = denied_key
        self.keys: list[str] = []

    def check(self, key: str):
        self.keys.append(key)
        return key != self.denied_key, 3.0 if key == self.denied_key else 0.0


def _agent(policy, limiter, bus, agent_id="skill-runtime"):
    return SkillOrchestraAgent(
        MagicMock(),
        "cloud-model",
        bus=bus,
        capability_policy=policy,
        rate_limiter=limiter,
        agent_id=agent_id,
    )


def _grant_local_execution(policy, agent_id="skill-runtime"):
    for capability in ("code:execute", "file:read", "file:write"):
        policy.grant(agent_id, capability)


def test_enhance_reasoning_denial_prevents_python_subprocess(monkeypatch):
    from openjarvis.agents.hybrid.skillorchestra import tools as tools_module

    policy = CapabilityPolicy(default_deny=True)
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent(policy, limiter, bus)
    call_alias = MagicMock()
    subprocess_run = MagicMock()
    monkeypatch.setattr(tools_module, "call_alias", call_alias)
    monkeypatch.setattr(tools_module.subprocess, "run", subprocess_run)

    result = run_code(
        agent,
        ModelSpec("reasoner-1", "model", "anthropic", "cloud"),
        context_str="context",
        problem="problem",
    )

    assert "code:execute" in result["exec_result"]
    call_alias.assert_not_called()
    subprocess_run.assert_not_called()
    assert limiter.keys == ["skill-runtime:skillorchestra_code"]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data
        == {
            "agent_id": "skill-runtime",
            "capability": "code:execute",
            "tool": "skillorchestra_code",
        }
        for event in bus.history
    )


def test_enhance_reasoning_requires_tempfile_capabilities(monkeypatch):
    from openjarvis.agents.hybrid.skillorchestra import tools as tools_module

    policy = CapabilityPolicy(default_deny=True)
    policy.grant("skill-runtime", "code:execute")
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent(policy, limiter, bus)
    call_alias = MagicMock()
    subprocess_run = MagicMock()
    monkeypatch.setattr(tools_module, "call_alias", call_alias)
    monkeypatch.setattr(tools_module.subprocess, "run", subprocess_run)

    result = run_code(
        agent,
        ModelSpec("reasoner-1", "model", "anthropic", "cloud"),
        context_str="context",
        problem="problem",
    )

    assert "file:read" in result["exec_result"]
    call_alias.assert_not_called()
    subprocess_run.assert_not_called()
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data["capability"] == "file:read"
        for event in bus.history
    )


def test_custom_retriever_rate_limit_prevents_http_post(monkeypatch):
    import requests

    from openjarvis.agents.hybrid.skillorchestra import tools as tools_module

    policy = CapabilityPolicy(default_deny=True)
    policy.grant("skill-runtime", "network:fetch")
    denied_key = "skill-runtime:skillorchestra_retriever"
    limiter = _Limiter(denied_key)
    bus = EventBus(record_history=True)
    agent = _agent(policy, limiter, bus)
    monkeypatch.setattr(
        tools_module,
        "call_alias",
        MagicMock(return_value=("<query>long enough query</query>", 1, 1, 0.0)),
    )
    post = MagicMock()
    monkeypatch.setattr(requests, "post", post)

    result = run_search(
        agent,
        ModelSpec("search-1", "model", "anthropic", "cloud"),
        context_str="context",
        problem="problem",
        retriever_url="https://retriever.example",
    )

    assert "Rate limit exceeded" in result["search_results_data"][0]
    post.assert_not_called()
    assert limiter.keys == [denied_key]
    assert any(
        event.event_type == EventType.RATE_LIMITED
        and event.data["agent_id"] == "skill-runtime"
        and event.data["tool"] == "skillorchestra_retriever"
        for event in bus.history
    )


def test_default_provider_search_denial_prevents_provider_call(monkeypatch):
    from openjarvis.agents.hybrid.skillorchestra import tools as tools_module

    policy = CapabilityPolicy(default_deny=True)
    _grant_local_execution(policy)
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent(policy, limiter, bus)
    monkeypatch.setattr(
        tools_module,
        "call_alias",
        MagicMock(return_value=("<query>long enough query</query>", 1, 1, 0.0)),
    )
    provider_search = MagicMock()
    monkeypatch.setattr(agent, "_call_anthropic_agent", provider_search)

    result = run_search(
        agent,
        ModelSpec("search-1", "model", "anthropic", "cloud"),
        context_str="context",
        problem="problem",
    )

    assert "network:fetch" in result["search_results_data"][0]
    provider_search.assert_not_called()
    assert limiter.keys == ["skill-runtime:skillorchestra_provider_search"]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data
        == {
            "agent_id": "skill-runtime",
            "capability": "network:fetch",
            "tool": "skillorchestra_provider_search",
        }
        for event in bus.history
    )


def test_tavily_search_denial_prevents_fetch(monkeypatch):
    from openjarvis.agents.hybrid.skillorchestra import tools as tools_module

    policy = CapabilityPolicy(default_deny=True)
    _grant_local_execution(policy)
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent(policy, limiter, bus)
    monkeypatch.setattr(
        tools_module,
        "call_alias",
        MagicMock(return_value=("<query>long enough query</query>", 1, 1, 0.0)),
    )
    tavily = MagicMock()
    monkeypatch.setattr(tools_module, "tavily_search_context", tavily)

    result = run_search(
        agent,
        ModelSpec("search-1", "model", "anthropic", "cloud"),
        context_str="context",
        problem="problem",
        search_backend="tavily",
    )

    assert "network:fetch" in result["search_results_data"][0]
    tavily.assert_not_called()
    assert limiter.keys == ["skill-runtime:skillorchestra_tavily"]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data["tool"] == "skillorchestra_tavily"
        for event in bus.history
    )


def test_provider_search_executes_with_positive_network_grant(monkeypatch):
    from openjarvis.agents.hybrid.skillorchestra import tools as tools_module

    policy = CapabilityPolicy(default_deny=True)
    policy.grant("skill-runtime", "network:fetch")
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent(policy, limiter, bus)
    monkeypatch.setattr(
        tools_module,
        "call_alias",
        MagicMock(return_value=("<query>long enough query</query>", 1, 1, 0.0)),
    )
    provider_search = MagicMock(return_value=("provider findings", 2, 3, 1, 1))
    monkeypatch.setattr(agent, "_call_anthropic_agent", provider_search)

    result = run_search(
        agent,
        ModelSpec("search-1", "model", "anthropic", "cloud"),
        context_str="context",
        problem="problem",
    )

    provider_search.assert_called_once()
    assert result["search_results_data"] == ["provider findings"]
    assert result["web_search_uses"] == 1
    assert limiter.keys == ["skill-runtime:skillorchestra_provider_search"]
    assert any(
        event.event_type == EventType.TOOL_CALL_START
        and event.data["tool"] == "skillorchestra_provider_search"
        for event in bus.history
    )


def test_tavily_search_executes_with_positive_network_grant(monkeypatch):
    from openjarvis.agents.hybrid.skillorchestra import tools as tools_module

    policy = CapabilityPolicy(default_deny=True)
    policy.grant("skill-runtime", "network:fetch")
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent(policy, limiter, bus)
    monkeypatch.setattr(
        tools_module,
        "call_alias",
        MagicMock(return_value=("<query>long enough query</query>", 1, 1, 0.0)),
    )
    tavily = MagicMock(
        return_value={"text": "tavily findings", "n_searches": 1, "cost_usd": 0.01}
    )
    monkeypatch.setattr(tools_module, "tavily_search_context", tavily)

    result = run_search(
        agent,
        ModelSpec("search-1", "model", "anthropic", "cloud"),
        context_str="context",
        problem="problem",
        search_backend="tavily",
    )

    tavily.assert_called_once_with("long enough query", max_results=5)
    assert result["search_results_data"] == ["tavily findings"]
    assert result["web_search_uses"] == 1
    assert limiter.keys == ["skill-runtime:skillorchestra_tavily"]


def test_retriever_configuration_is_derived_before_agent_run():
    policy = CapabilityPolicy(default_deny=True)
    _grant_local_execution(policy, "restricted-skill")
    limiter = _Limiter()
    agent = SkillOrchestraAgent(
        MagicMock(),
        "cloud-model",
        cfg={"retriever_url": "https://retriever.example"},
        capability_policy=policy,
        rate_limiter=limiter,
        agent_id="restricted-skill",
    )
    agent._run_paradigm = MagicMock(return_value=("should not run", {}))

    result = agent.run("research")

    assert "network:fetch" in result.content
    agent._run_paradigm.assert_not_called()
    assert limiter.keys == ["restricted-skill:hybrid_agent_run"]


def test_default_provider_search_is_derived_before_agent_run():
    policy = CapabilityPolicy(default_deny=True)
    _grant_local_execution(policy, "restricted-skill")
    limiter = _Limiter()
    agent = SkillOrchestraAgent(
        MagicMock(),
        "cloud-model",
        capability_policy=policy,
        rate_limiter=limiter,
        agent_id="restricted-skill",
    )
    agent._run_paradigm = MagicMock(return_value=("should not run", {}))

    result = agent.run("research")

    assert "network:fetch" in result.content
    agent._run_paradigm.assert_not_called()
    assert limiter.keys == ["restricted-skill:hybrid_agent_run"]
