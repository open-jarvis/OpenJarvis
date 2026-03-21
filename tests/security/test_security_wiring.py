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
from openjarvis.security import setup_security


class _ConcreteAgent(ToolUsingAgent):
    """Minimal concrete subclass — ToolUsingAgent is abstract."""

    agent_id = "test"

    def run(self, input, context=None, **kwargs):
        return AgentResult(content="ok")


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
