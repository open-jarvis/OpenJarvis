"""Verify security wiring reaches agents and ToolExecutor."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents._stubs import AgentResult, ToolUsingAgent
from openjarvis.core.config import (
    CapabilitiesConfig,
    JarvisConfig,
    SecurityConfig,
)
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolCall
from openjarvis.security import setup_security
from openjarvis.security.capabilities import CapabilityPolicy
from openjarvis.system import JarvisSystem
from openjarvis.tools.repl import ReplTool


class _ConcreteAgent(ToolUsingAgent):
    """Minimal concrete subclass — ToolUsingAgent is abstract."""

    agent_id = "test"

    def run(self, input, context=None, **kwargs):
        return AgentResult(content="ok")


class _CallingAgent(ToolUsingAgent):
    agent_id = "class-default-identity"

    def run(self, input, context=None, **kwargs):
        result = self._executor.execute(
            ToolCall(
                id="agent-repl-denied",
                name="repl",
                arguments='{"code": "sentinel = 42"}',
            )
        )
        return AgentResult(content=result.content, tool_results=[result])


class _RecordingLimiter:
    def __init__(self) -> None:
        self.keys = []

    def check(self, key):
        self.keys.append(key)
        return True, 0.0


def _make_mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "ok",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "model": "m",
        "finish_reason": "stop",
    }
    engine.list_models.return_value = ["m"]
    engine.health.return_value = True
    return engine


def _has_rust() -> bool:
    try:
        import openjarvis_rust  # noqa: F401

        return True
    except ImportError:
        return False


class TestCapabilityPolicyReachesExecutor:
    def test_no_policy_when_caps_disabled(self) -> None:
        cfg = JarvisConfig()
        cfg.security = SecurityConfig(
            enabled=True,
            capabilities=CapabilitiesConfig(enabled=False),
        )
        bus = EventBus()
        engine = _make_mock_engine()
        sec = setup_security(cfg, engine, bus)

        agent = _ConcreteAgent(
            sec.engine,
            "m",
            tools=[],
            capability_policy=sec.capability_policy,
        )
        assert agent._executor._capability_policy is None

    def test_no_policy_when_security_disabled(self) -> None:
        cfg = JarvisConfig()
        cfg.security = SecurityConfig(enabled=False)
        engine = _make_mock_engine()
        sec = setup_security(cfg, engine)

        agent = _ConcreteAgent(
            sec.engine,
            "m",
            tools=[],
            capability_policy=sec.capability_policy,
        )
        assert agent._executor._capability_policy is None
        # Engine should be the original, unwrapped
        assert sec.engine is engine

    def test_orchestrator_propagates_runtime_identity_and_limiter(self) -> None:
        key = "restricted-orchestrator-agent"
        AgentRegistry.register_value(key, _CallingAgent)
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("_default", "code:execute")
        policy.deny(key, "code:execute")
        limiter = _RecordingLimiter()
        repl = ReplTool()
        config = JarvisConfig()
        config.agent.context_from_memory = False
        config.traces.enabled = False
        system = JarvisSystem(
            config=config,
            bus=EventBus(),
            engine=_make_mock_engine(),
            engine_key="mock",
            model="m",
            agent_name=key,
            tools=[repl],
            capability_policy=policy,
            rate_limiter=limiter,
        )

        result = system.ask("run")

        assert "code:execute" in result["content"]
        assert "denied" in result["content"]
        assert limiter.keys == [f"{key}:repl"]
        assert repl._sessions == {}

    def test_cli_ask_propagates_runtime_identity_and_limiter(self, monkeypatch) -> None:
        import importlib

        ask_module = importlib.import_module("openjarvis.cli.ask")

        key = "restricted-cli-ask-agent"
        AgentRegistry.register_value(key, _CallingAgent)
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("_default", "code:execute")
        policy.deny(key, "code:execute")
        limiter = _RecordingLimiter()
        repl = ReplTool()
        config = JarvisConfig()
        config.agent.context_from_memory = False
        monkeypatch.setattr(ask_module, "_build_tools", lambda *args: [repl])
        monkeypatch.setattr(
            "openjarvis.mcp.loader.load_mcp_tools_from_config",
            lambda *args, **kwargs: ([], []),
        )

        result = ask_module._run_agent(
            key,
            "run",
            _make_mock_engine(),
            "m",
            ["repl"],
            config,
            EventBus(),
            0.1,
            32,
            capability_policy=policy,
            rate_limiter=limiter,
        )

        assert "code:execute" in result.content
        assert "denied" in result.content
        assert limiter.keys == [f"{key}:repl"]
        assert repl._sessions == {}
