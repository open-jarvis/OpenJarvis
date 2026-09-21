"""Security regressions for ToolOrchestra worker/action dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import openjarvis.agents.hybrid.toolorchestra as toolorchestra_module
from openjarvis.agents.hybrid.toolorchestra import ToolOrchestraAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.security.capabilities import CapabilityPolicy


class _Limiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def check(self, key: str):
        self.keys.append(key)
        return True, 0.0


def _agent(cfg, policy, limiter, bus, agent_id="tool-runtime"):
    agent = ToolOrchestraAgent(
        MagicMock(),
        "claude-opus-4-7",
        cfg=cfg,
        bus=bus,
        capability_policy=policy,
        rate_limiter=limiter,
        agent_id=agent_id,
    )
    agent._run_paradigm = MagicMock(return_value=("should not run", {}))
    return agent


def _assert_denied(agent, bus, capability):
    result = agent.run("research")

    assert capability in result.content
    agent._run_paradigm.assert_not_called()
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data
        == {
            "agent_id": "tool-runtime",
            "capability": capability,
            "tool": "hybrid_agent_run",
        }
        for event in bus.history
    )


def test_default_hosted_search_pool_requires_network_capability():
    policy = CapabilityPolicy(default_deny=True)
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent({}, policy, limiter, bus)

    _assert_denied(agent, bus, "network:fetch")

    assert limiter.keys == ["tool-runtime:hybrid_agent_run"]


def test_custom_tavily_worker_requires_network_even_with_provider_backend():
    policy = CapabilityPolicy(default_deny=True)
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    cfg = {
        "search_backend": "provider",
        "worker_pool": [
            {"id": 0, "name": "search", "type": "tavily-search"},
            {
                "id": 1,
                "name": "solver",
                "type": "anthropic",
                "model": "claude-opus-4-7",
            },
        ],
    }
    agent = _agent(cfg, policy, limiter, bus)

    _assert_denied(agent, bus, "network:fetch")

    assert limiter.keys == ["tool-runtime:hybrid_agent_run"]


def test_rl_paper_pool_requires_code_after_network_is_granted():
    policy = CapabilityPolicy(default_deny=True)
    policy.grant("tool-runtime", "network:fetch")
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent(
        {"orchestrator_mode": "rl", "pool": "paper"},
        policy,
        limiter,
        bus,
    )

    _assert_denied(agent, bus, "code:execute")

    assert limiter.keys == ["tool-runtime:hybrid_agent_run"]


def test_selected_search_worker_is_gated_again_at_dispatch(monkeypatch):
    policy = CapabilityPolicy(default_deny=True)
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent({}, policy, limiter, bus)
    raw_dispatch = MagicMock()
    monkeypatch.setattr(toolorchestra_module, "_call_worker", raw_dispatch)

    result = agent._call_worker_secured(
        {
            "name": "web-search",
            "type": "anthropic-web-search",
            "model": "claude-haiku-4-5",
        },
        "query",
        {},
    )

    assert "network:fetch" in result[0]
    raw_dispatch.assert_not_called()
    assert limiter.keys == ["tool-runtime:toolorchestra_worker"]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data["tool"] == "toolorchestra_worker"
        and event.data["capability"] == "network:fetch"
        for event in bus.history
    )


def test_paper_python_is_gated_immediately_before_modal(monkeypatch):
    policy = CapabilityPolicy(default_deny=True)
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent(
        {"orchestrator_mode": "rl", "pool": "paper"},
        policy,
        limiter,
        bus,
    )
    raw_modal = MagicMock()
    monkeypatch.setattr(toolorchestra_module, "_call_modal_python", raw_modal)

    output, returncode = agent._call_modal_python_secured("print(42)", timeout_s=3)

    assert "code:execute" in output
    assert returncode == -1
    raw_modal.assert_not_called()
    assert limiter.keys == ["tool-runtime:toolorchestra_modal_python"]


def test_swe_worker_requires_file_caps_before_local_execution(monkeypatch):
    policy = CapabilityPolicy(default_deny=True)
    for capability in ("code:execute", "file:read"):
        policy.grant("tool-runtime", capability)
    limiter = _Limiter()
    bus = EventBus(record_history=True)
    agent = _agent({}, policy, limiter, bus)
    raw_swe_dispatch = MagicMock()
    monkeypatch.setattr(toolorchestra_module, "_swe_call_worker", raw_swe_dispatch)

    result = agent._swe_call_worker_secured(
        {
            "name": "local-coder",
            "type": "vllm",
            "model": "local-model",
        },
        "solve",
        {},
        {"problem_statement": "fix it"},
        Path("/tmp/worktree-probe"),
        1,
    )

    assert "file:write" in result[0]
    raw_swe_dispatch.assert_not_called()
    assert limiter.keys == ["tool-runtime:toolorchestra_swe_worker"]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data["tool"] == "toolorchestra_swe_worker"
        and event.data["capability"] == "file:write"
        for event in bus.history
    )
