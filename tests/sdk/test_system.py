"""Tests for the composition layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus
from openjarvis.system import JarvisSystem, SystemBuilder


class TestJarvisSystem:
    def test_ask_direct_mode(self):
        engine = MagicMock()
        engine.generate.return_value = {
            "content": "Hello!",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test-model",
        )
        result = system.ask("Hi")
        assert result["content"] == "Hello!"
        assert result["model"] == "test-model"
        assert result["engine"] == "mock"

    def test_ask_returns_usage(self):
        engine = MagicMock()
        engine.generate.return_value = {
            "content": "OK",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
        )
        result = system.ask("Hi")
        assert result["usage"]["prompt_tokens"] == 10

    def test_ask_no_agent_direct_mode(self):
        """When agent_name is empty and no agent param, use direct engine mode."""
        engine = MagicMock()
        engine.generate.return_value = {
            "content": "Direct response",
            "usage": {},
        }
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            agent_name="",
        )
        result = system.ask("Hi")
        assert result["content"] == "Direct response"
        engine.generate.assert_called_once()

    def test_ask_with_agent_none_uses_direct(self):
        """Passing agent_name='none' should use direct engine mode."""
        engine = MagicMock()
        engine.generate.return_value = {
            "content": "Direct response",
            "usage": {},
        }
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            agent_name="none",
        )
        result = system.ask("Hi")
        assert result["content"] == "Direct response"

    def test_ask_with_agent_override(self):
        """Passing agent= param should use that agent even if system has a default."""
        from openjarvis.agents._stubs import AgentResult
        from openjarvis.core.registry import AgentRegistry

        class TestAgent:
            agent_id = "test-system-agent"

            def __init__(self, eng, model, **kwargs):
                pass

            def run(self, input, context=None, **kwargs):
                return AgentResult(content="From test agent", turns=1)

        # Register (or re-register) the agent
        if not AgentRegistry.contains("test-system-agent"):
            AgentRegistry.register_value("test-system-agent", TestAgent)

        engine = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            agent_name="",
        )
        result = system.ask("Hi", agent="test-system-agent")
        assert result["content"] == "From test agent"

    def test_ask_unknown_agent(self):
        """Unknown agent should return an error dict."""
        engine = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
        )
        result = system.ask("Hi", agent="nonexistent-agent-xyz")
        assert "Unknown agent" in result["content"]
        assert result.get("error") is True

    def test_ask_passes_temperature_and_max_tokens(self):
        engine = MagicMock()
        engine.generate.return_value = {"content": "OK", "usage": {}}
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
        )
        system.ask("Hi", temperature=0.3, max_tokens=512)
        call_kwargs = engine.generate.call_args
        assert call_kwargs[1]["temperature"] == 0.3
        assert call_kwargs[1]["max_tokens"] == 512

    def test_close(self):
        engine = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
        )
        system.close()  # Should not raise

    def test_close_with_telemetry(self):
        engine = MagicMock()
        telem = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            telemetry_store=telem,
        )
        system.close()
        telem.close.assert_called_once()

    def test_close_with_trace_store(self):
        engine = MagicMock()
        trace = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            trace_store=trace,
        )
        system.close()
        trace.close.assert_called_once()

    def test_build_tools_empty(self):
        engine = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
        )
        tools = system._build_tools([])
        assert tools == []

    def test_build_tools_unknown_tool(self):
        engine = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
        )
        tools = system._build_tools(["nonexistent_tool_xyz"])
        assert tools == []


class TestSystemBuilder:
    def test_builder_fluent_api(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        result = builder.engine("ollama").model("test").agent("simple")
        assert result is builder  # fluent

    def test_builder_stores_config(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        assert builder._config is config

    def test_builder_engine_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        builder.engine("vllm")
        assert builder._engine_key == "vllm"

    def test_builder_model_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        builder.model("my-model")
        assert builder._model == "my-model"

    def test_builder_agent_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        builder.agent("orchestrator")
        assert builder._agent_name == "orchestrator"

    def test_builder_tools_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        builder.tools(["calculator", "think"])
        assert builder._tool_names == ["calculator", "think"]

    def test_builder_telemetry_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        builder.telemetry(False)
        assert builder._telemetry is False

    def test_builder_traces_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        builder.traces(True)
        assert builder._traces is True

    def test_builder_event_bus_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        bus = EventBus()
        builder.event_bus(bus)
        assert builder._bus is bus

    def test_builder_chaining(self):
        config = JarvisConfig()
        builder = (
            SystemBuilder(config)
            .engine("ollama")
            .model("test-model")
            .agent("simple")
            .tools(["calculator"])
            .telemetry(True)
            .traces(False)
        )
        assert builder._engine_key == "ollama"
        assert builder._model == "test-model"
        assert builder._agent_name == "simple"
        assert builder._tool_names == ["calculator"]
        assert builder._telemetry is True
        assert builder._traces is False

    def test_import_works(self):
        from openjarvis.system import JarvisSystem, SystemBuilder

        assert JarvisSystem is not None
        assert SystemBuilder is not None

    def test_builder_default_config(self):
        """SystemBuilder with no config should load defaults."""
        builder = SystemBuilder()
        assert builder._config is not None
        assert isinstance(builder._config, JarvisConfig)

    def test_builder_build_raises_without_engine(self):
        """build() should raise RuntimeError when no engine is available."""
        config = JarvisConfig()
        # Use a nonsense engine key to ensure no engine is found
        builder = SystemBuilder(config).engine("nonexistent_engine_xyz_123")
        with pytest.raises(RuntimeError, match="No inference engine"):
            builder.build()

    def test_builder_sandbox_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        result = builder.sandbox(True)
        assert result is builder  # fluent
        assert builder._sandbox is True

    def test_builder_scheduler_setter(self):
        config = JarvisConfig()
        builder = SystemBuilder(config)
        result = builder.scheduler(True)
        assert result is builder  # fluent
        assert builder._scheduler is True

    def test_builder_sandbox_scheduler_chaining(self):
        config = JarvisConfig()
        builder = (
            SystemBuilder(config)
            .engine("ollama")
            .model("test")
            .sandbox(True)
            .scheduler(True)
        )
        assert builder._sandbox is True
        assert builder._scheduler is True
        assert builder._engine_key == "ollama"


class TestSystemBuilderEngineInstance:
    """Explicit engine injection (jarvis eval --base-url path)."""

    @staticmethod
    def _fake_engine(healthy: bool = True) -> MagicMock:
        engine = MagicMock(
            spec=["health", "can_serve", "generate", "list_models", "close"]
        )
        engine.health.return_value = healthy
        engine._host = "http://127.0.0.1:18999"
        return engine

    def test_engine_instance_is_fluent(self):
        builder = SystemBuilder(JarvisConfig())
        engine = self._fake_engine()
        result = builder.engine_instance(engine, key="my-endpoint")
        assert result is builder
        assert builder._engine_instance is engine
        assert builder._engine_instance_key == "my-endpoint"

    def test_resolve_engine_returns_injected_instance(self):
        config = JarvisConfig()
        engine = self._fake_engine(healthy=True)
        builder = SystemBuilder(config).engine_instance(engine, key="endpoint")
        resolved_engine, resolved_key = builder._resolve_engine(config)
        assert resolved_engine is engine
        assert resolved_key == "endpoint"

    def test_unhealthy_injected_instance_raises_naming_host(self):
        config = JarvisConfig()
        engine = self._fake_engine(healthy=False)
        builder = SystemBuilder(config).engine_instance(engine, key="endpoint")
        with pytest.raises(RuntimeError, match=r"http://127\.0\.0\.1:18999"):
            builder._resolve_engine(config)

    def test_unhealthy_injected_instance_never_consults_discovery(self):
        """The observed failure mode: an explicit endpoint must NOT be
        silently replaced by whatever other engine discovery finds."""
        config = JarvisConfig()
        engine = self._fake_engine(healthy=False)
        builder = SystemBuilder(config).engine_instance(engine)
        with patch("openjarvis.engine._discovery.get_engine") as mock_get_engine:
            with pytest.raises(RuntimeError, match="Refusing to fall back"):
                builder._resolve_engine(config)
        mock_get_engine.assert_not_called()

    def test_healthy_injected_instance_never_consults_discovery(self):
        config = JarvisConfig()
        engine = self._fake_engine(healthy=True)
        builder = SystemBuilder(config).engine_instance(engine, key="endpoint")
        with patch("openjarvis.engine._discovery.get_engine") as mock_get_engine:
            resolved_engine, _ = builder._resolve_engine(config)
        assert resolved_engine is engine
        mock_get_engine.assert_not_called()

    def test_build_wires_injected_engine(self):
        """build() must use the injected engine (possibly behind security
        wrappers) instead of running discovery."""
        config = JarvisConfig()
        engine = self._fake_engine(healthy=True)
        engine.list_models.return_value = ["stub-model"]
        builder = (
            SystemBuilder(config)
            .engine_instance(engine, key="endpoint")
            .model("stub-model")
            .telemetry(False)
            .traces(False)
        )
        system = builder.build()
        try:
            inner = system.engine
            while hasattr(inner, "_engine"):
                inner = inner._engine
            assert inner is engine
            assert system.engine_key == "endpoint"
        finally:
            system.close()


class TestJarvisSystemClose:
    def test_close_with_scheduler_store(self):
        engine = MagicMock()
        sched_store = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            scheduler_store=sched_store,
        )
        system.close()
        sched_store.close.assert_called_once()

    def test_close_with_scheduler(self):
        engine = MagicMock()
        scheduler = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            scheduler=scheduler,
        )
        system.close()
        scheduler.stop.assert_called_once()

    def test_close_with_memory_backend(self):
        engine = MagicMock()
        mem = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            memory_backend=mem,
        )
        system.close()
        mem.close.assert_called_once()

    def test_close_with_session_store(self):
        engine = MagicMock()
        sess = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            session_store=sess,
        )
        system.close()
        sess.close.assert_called_once()

    def test_close_with_workflow_engine(self):
        engine = MagicMock()
        wf = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            workflow_engine=wf,
        )
        system.close()
        wf.close.assert_called_once()

    def test_system_fields_default_none(self):
        engine = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
        )
        assert system.scheduler_store is None
        assert system.scheduler is None
        assert system.container_runner is None

    def test_close_with_agent_scheduler(self):
        engine = MagicMock()
        agent_scheduler = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
            agent_scheduler=agent_scheduler,
        )
        system.close()
        agent_scheduler.stop.assert_called_once()

    def test_system_agent_fields_default_none(self):
        engine = MagicMock()
        system = JarvisSystem(
            config=JarvisConfig(),
            bus=EventBus(),
            engine=engine,
            engine_key="mock",
            model="test",
        )
        assert system.agent_scheduler is None
        assert system.agent_executor is None
