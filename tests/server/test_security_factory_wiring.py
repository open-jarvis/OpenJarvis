"""Adversarial security wiring tests for the programmatic app factory."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus, EventType
from openjarvis.security import SecurityContext
from openjarvis.security.capabilities import CapabilityPolicy
from openjarvis.server.app import create_app


def _config() -> JarvisConfig:
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    config.security.enabled = True
    return config


def _runtime_config() -> JarvisConfig:
    """Factory config without external analytics or derived security."""
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    config.security.enabled = False
    return config


def test_factory_derives_missing_security_and_secures_prebuilt_agent(
    monkeypatch,
) -> None:
    engine = MagicMock(name="raw-engine")
    wrapped = MagicMock(name="wrapped-engine")
    policy = object()
    limiter = object()
    audit = object()
    setup = MagicMock(
        return_value=SecurityContext(
            engine=wrapped,
            capability_policy=policy,
            rate_limiter=limiter,
            audit_logger=audit,
        )
    )
    monkeypatch.setattr("openjarvis.security.setup_security", setup)
    agent = SimpleNamespace(
        agent_id="tool-agent",
        _engine=engine,
        _executor=SimpleNamespace(
            _capability_policy=None,
            _rate_limiter=None,
            _agent_id="",
        ),
    )

    app = create_app(engine, "model", agent=agent, config=_config())

    setup.assert_called_once()
    assert app.state.engine is wrapped
    assert app.state.bus is not None
    assert app.state.capability_policy is policy
    assert app.state.rate_limiter is limiter
    assert app.state.audit_logger is audit
    assert agent._engine is wrapped
    assert agent._bus is app.state.bus
    assert agent._executor._bus is app.state.bus
    assert agent._executor._capability_policy is policy
    assert agent._executor._rate_limiter is limiter
    assert agent._executor._agent_id == "tool-agent"


def test_factory_preserves_explicit_security_primitives(monkeypatch) -> None:
    derived_policy = object()
    derived_limiter = object()
    derived_audit = object()
    explicit_policy = object()
    explicit_limiter = object()
    setup = MagicMock(
        return_value=SecurityContext(
            engine="wrapped",
            capability_policy=derived_policy,
            rate_limiter=derived_limiter,
            audit_logger=derived_audit,
        )
    )
    monkeypatch.setattr("openjarvis.security.setup_security", setup)

    app = create_app(
        "raw",
        "model",
        config=_config(),
        capability_policy=explicit_policy,
        rate_limiter=explicit_limiter,
    )

    assert app.state.engine == "wrapped"
    assert app.state.capability_policy is explicit_policy
    assert app.state.rate_limiter is explicit_limiter
    assert app.state.audit_logger is derived_audit


def test_factory_propagates_strict_security_setup_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.security.setup_security",
        MagicMock(side_effect=RuntimeError("policy failed")),
    )

    with pytest.raises(RuntimeError, match="policy failed"):
        create_app("raw", "model", config=_config())


def test_factory_synchronizes_prebuilt_rlm_lazy_executor_runtime(monkeypatch) -> None:
    from openjarvis.agents.rlm import RLMAgent
    from openjarvis.agents.rlm_repl import RLMRepl

    engine = MagicMock()
    engine.generate.side_effect = [
        {"content": "```python\nsentinel = 42\n```", "finish_reason": "stop"},
        {"content": "finished", "finish_reason": "stop"},
    ]
    bus = EventBus(record_history=True)
    policy = CapabilityPolicy(default_deny=True)
    # Permit the top-level agent gate, but not the lazily-created REPL tool.
    policy.grant("server-rlm", "code:execute", "agent_run")

    class _Limiter:
        def __init__(self):
            self.keys = []

        def check(self, key):
            self.keys.append(key)
            return True, 0.0

    limiter = _Limiter()
    agent = RLMAgent(engine, "model")
    repl_execute = MagicMock(return_value="should not execute")
    monkeypatch.setattr(RLMRepl, "execute", repl_execute)

    app = create_app(
        engine,
        "model",
        agent=agent,
        agent_name="server-rlm",
        bus=bus,
        capability_policy=policy,
        rate_limiter=limiter,
        config=_runtime_config(),
    )
    result = app.state.agent.run("execute generated code")

    assert result.content == "finished"
    repl_execute.assert_not_called()
    assert agent._runtime_bus is bus
    assert agent._runtime_capability_policy is policy
    assert agent._runtime_rate_limiter is limiter
    assert agent._runtime_agent_id == "server-rlm"
    assert limiter.keys == [
        "server-rlm:agent_run",
        "server-rlm:rlm_repl",
    ]
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data
        == {
            "agent_id": "server-rlm",
            "capability": "code:execute",
            "tool": "rlm_repl",
        }
        for event in bus.history
    )


def test_factory_preserves_prebuilt_rlm_policy_and_limiter_while_reidentifying() -> (
    None
):
    from openjarvis.agents.rlm import RLMAgent

    engine = MagicMock()
    agent_policy = CapabilityPolicy(default_deny=True)
    server_policy = CapabilityPolicy(default_deny=True)
    agent_limiter = object()
    server_limiter = object()
    agent = RLMAgent(
        engine,
        "model",
        capability_policy=agent_policy,
        rate_limiter=agent_limiter,
        agent_id="prebuilt-id",
    )

    create_app(
        engine,
        "model",
        agent=agent,
        agent_name="server-id",
        capability_policy=server_policy,
        rate_limiter=server_limiter,
        config=_runtime_config(),
    )

    assert agent._capability_policy is agent_policy
    assert agent._runtime_capability_policy is agent_policy
    assert agent._rate_limiter is agent_limiter
    assert agent._runtime_rate_limiter is agent_limiter
    assert agent._runtime_agent_id == "server-id"


def test_factory_overrides_prebuilt_executor_identity_at_server_boundary() -> None:
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.core.types import ToolCall, ToolResult
    from openjarvis.tools._stubs import BaseTool, ToolSpec

    class _AdminTool(BaseTool):
        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name="tenant_admin_probe",
                description="Identity regression probe.",
                required_capabilities=["system:admin"],
            )

        def execute(self, **params) -> ToolResult:
            return ToolResult(tool_name=self.spec.name, content="executed")

    engine = MagicMock()
    bus = EventBus(record_history=True)
    policy = CapabilityPolicy(default_deny=True)
    # This grant demonstrates the bypass: the prebuilt class-default identity
    # is privileged, while the identity assigned by the server is not.
    policy.grant("orchestrator", "system:admin", "tenant_admin_probe")
    agent = OrchestratorAgent(engine, "model", tools=[_AdminTool()])
    assert agent._executor._agent_id == "orchestrator"

    create_app(
        engine,
        "model",
        agent=agent,
        agent_name="tenant-denied",
        bus=bus,
        capability_policy=policy,
        config=_runtime_config(),
    )
    result = agent._executor.execute(
        ToolCall(id="identity-probe", name="tenant_admin_probe", arguments="{}")
    )

    assert not result.success
    assert "system:admin" in result.content
    assert agent._runtime_agent_id == "tenant-denied"
    assert agent._executor._agent_id == "tenant-denied"
    assert any(
        event.event_type == EventType.CAPABILITY_DENIED
        and event.data
        == {
            "agent_id": "tenant-denied",
            "capability": "system:admin",
            "tool": "tenant_admin_probe",
        }
        for event in bus.history
    )
