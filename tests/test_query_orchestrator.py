"""Isolated QueryOrchestrator tests using a minimal fake system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus
from openjarvis.system import QueryOrchestrator


class _FakeEngine:
    def __init__(self, reply: Dict[str, Any]) -> None:
        self._reply = reply
        self.calls: List[Dict[str, Any]] = []

    def generate(self, messages, *, model, temperature, max_tokens, **_):
        self.calls.append(
            {
                "messages": list(messages),
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self._reply

    def list_models(self):
        return []


@dataclass
class _FakeSystem:
    """Minimum surface QueryOrchestrator reads — no subsystems wired."""

    config: JarvisConfig = field(default_factory=JarvisConfig)
    bus: EventBus = field(default_factory=EventBus)
    engine: Any = None
    engine_key: str = "fake"
    model: str = "fake-model"
    agent_name: str = ""
    tools: List[Any] = field(default_factory=list)
    memory_backend: Optional[Any] = None
    capability_policy: Optional[Any] = None
    session_store: Optional[Any] = None
    trace_store: Optional[Any] = None
    trace_collector: Optional[Any] = None
    _skill_few_shot_examples: Optional[List[str]] = None


class TestAskDirectEngineMode:
    def test_direct_engine_returns_content(self):
        engine = _FakeEngine({"content": "hi there", "usage": {"tokens": 4}})
        system = _FakeSystem(engine=engine)
        orchestrator = QueryOrchestrator(system)

        result = orchestrator.ask("hello", context=False)

        assert result["content"] == "hi there"
        assert result["usage"] == {"tokens": 4}
        assert result["model"] == "fake-model"
        assert result["engine"] == "fake"

    def test_forwards_temperature_and_max_tokens(self):
        engine = _FakeEngine({"content": ""})
        system = _FakeSystem(engine=engine)
        orchestrator = QueryOrchestrator(system)

        orchestrator.ask("q", context=False, temperature=0.9, max_tokens=128)

        assert engine.calls[0]["temperature"] == 0.9
        assert engine.calls[0]["max_tokens"] == 128

    def test_uses_config_defaults_when_omitted(self):
        engine = _FakeEngine({"content": ""})
        config = JarvisConfig()
        config.intelligence.temperature = 0.42
        config.intelligence.max_tokens = 77
        system = _FakeSystem(config=config, engine=engine)
        orchestrator = QueryOrchestrator(system)

        orchestrator.ask("q", context=False)

        assert engine.calls[0]["temperature"] == 0.42
        assert engine.calls[0]["max_tokens"] == 77


class TestAskAgentRouting:
    def test_agent_none_stays_on_engine(self):
        engine = _FakeEngine({"content": "engine path"})
        system = _FakeSystem(engine=engine, agent_name="none")
        orchestrator = QueryOrchestrator(system)

        result = orchestrator.ask("plain question", context=False)

        assert result["content"] == "engine path"
        assert len(engine.calls) == 1

    def test_unknown_agent_returns_error_dict(self):
        engine = _FakeEngine({"content": ""})
        system = _FakeSystem(engine=engine, agent_name="does_not_exist")
        orchestrator = QueryOrchestrator(system)

        result = orchestrator.ask("q", context=False)

        assert result.get("error") is True
        assert "does_not_exist" in result["content"]


class TestDetectAgentIntent:
    @pytest.mark.parametrize(
        "query",
        [
            "good morning",
            "morning digest please",
            "can you run the daily briefing",
            "morning briefing time",
        ],
    )
    def test_morning_digest_triggers(self, query):
        from openjarvis.core.registry import AgentRegistry

        # Register a stub so the intent check returns the name.
        try:
            AgentRegistry.get("morning_digest")
            registered = True
        except KeyError:
            registered = False

        system = _FakeSystem()
        orchestrator = QueryOrchestrator(system)
        detected = orchestrator._detect_agent_intent(query)

        if registered:
            assert detected == "morning_digest"
        else:
            assert detected is None

    def test_plain_query_returns_none(self):
        system = _FakeSystem()
        orchestrator = QueryOrchestrator(system)
        assert orchestrator._detect_agent_intent("what's the weather") is None
