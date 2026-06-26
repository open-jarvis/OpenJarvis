"""Tests for model resolution fallback chain in jarvis ask."""

from __future__ import annotations

import importlib
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.events import EventBus, EventType

_ask_mod = importlib.import_module("openjarvis.cli.ask")


def _mock_engine():
    """Create a mock engine that returns a simple response."""
    engine = mock.MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": "Hello!",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


def _register_agents():
    """Re-register agents after the conftest registry clear.

    The default ``JarvisConfig().agent.default_agent`` is ``"simple"``,
    so ``jarvis ask "..."`` (without ``--agent``) routes through SimpleAgent.
    Without this re-registration, that path raises ``Unknown agent: simple``.
    """
    from openjarvis.agents.simple import SimpleAgent
    from openjarvis.core.registry import AgentRegistry

    if not AgentRegistry.contains("simple"):
        AgentRegistry.register_value("simple", SimpleAgent)


def _patch_engine(engine):
    """Return context managers that patch engine discovery to use our mock."""
    _register_agents()
    return (
        mock.patch.object(
            _ask_mod,
            "get_engine",
            return_value=("mock", engine),
        ),
        mock.patch.object(
            _ask_mod,
            "discover_engines",
            return_value={"mock": engine},
        ),
        mock.patch.object(
            _ask_mod,
            "discover_models",
            return_value={"mock": ["test-model"]},
        ),
        mock.patch.object(_ask_mod, "register_builtin_models"),
        mock.patch.object(_ask_mod, "merge_discovered_models"),
        mock.patch.object(_ask_mod, "TelemetryStore"),
    )


class TestAskModelResolution:
    def test_route_trace_event_published(self) -> None:
        engine = _mock_engine()
        patches = _patch_engine(engine)
        bus = EventBus(record_history=True)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            mock.patch.object(_ask_mod, "EventBus", return_value=bus),
        ):
            result = CliRunner().invoke(cli, ["ask", "Please classify this ticket"])
        assert result.exit_code == 0
        route_events = [
            e
            for e in bus.history
            if e.event_type == EventType.TRACE_STEP
            and e.data.get("step_type") == "route"
        ]
        assert route_events, "expected a route TRACE_STEP event"
        ev = route_events[-1]
        assert ev.data["output"]["model"]
        assert "selected_engine" in ev.data["output"]
        assert "escalation_chain" in ev.data["output"]

    def test_default_model_from_config(self) -> None:
        """When no -m flag, uses config.intelligence.default_model."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0
        assert "Hello!" in result.output

    def test_explicit_model_flag(self) -> None:
        """The -m flag directly selects a model, bypassing fallback chain."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = CliRunner().invoke(
                cli,
                ["ask", "-m", "test-model", "Hello"],
            )
        assert result.exit_code == 0
        assert "Hello!" in result.output

    def test_fallback_to_engine_models(self) -> None:
        """When default_model is empty, falls back to first engine model."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            mock.patch.object(
                _ask_mod,
                "load_config",
            ) as mock_config,
        ):
            cfg = mock_config.return_value
            cfg.telemetry.enabled = False
            cfg.intelligence.default_model = ""
            cfg.intelligence.fallback_model = ""
            cfg.intelligence.temperature = 0.7
            cfg.intelligence.max_tokens = 1024
            cfg.agent.context_from_memory = False
            cfg.agent.default_agent = ""
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0

    def test_missing_default_prefers_configured_fallback(self) -> None:
        """If default_model is unavailable, prefer fallback_model over local models."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            mock.patch.object(
                _ask_mod,
                "load_config",
            ) as mock_config,
        ):
            cfg = mock_config.return_value
            cfg.telemetry.enabled = False
            cfg.intelligence.default_model = "missing-local-model"
            cfg.intelligence.fallback_model = "openrouter/free"
            cfg.intelligence.temperature = 0.7
            cfg.intelligence.max_tokens = 1024
            cfg.agent.context_from_memory = False
            cfg.agent.default_agent = ""
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0
        assert engine.generate.call_args.kwargs["model"] == "openrouter/free"

    def test_fallback_to_fallback_model(self) -> None:
        """When default_model is empty and no engine models, uses fallback_model."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        # Override discover_models to return empty list
        with (
            patches[0],
            patches[1],
            mock.patch.object(
                _ask_mod,
                "discover_models",
                return_value={"mock": []},
            ),
            patches[3],
            patches[4],
            patches[5],
            mock.patch.object(
                _ask_mod,
                "load_config",
            ) as mock_config,
        ):
            cfg = mock_config.return_value
            cfg.telemetry.enabled = False
            cfg.intelligence.default_model = ""
            cfg.intelligence.fallback_model = "fallback-model"
            cfg.intelligence.temperature = 0.7
            cfg.intelligence.max_tokens = 1024
            cfg.agent.context_from_memory = False
            cfg.agent.default_agent = ""
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0

    def test_cloud_fallback_reselects_engine(self) -> None:
        """A cloud fallback model must re-select the cloud engine.

        Regression for the local-engine-up-but-default-missing path: the engine
        is first resolved against the (missing) ``default_model`` and lands on
        the local engine, whose ``can_serve`` is ``False`` for ``openrouter/``
        ids. ``ask`` must then re-resolve so the request actually runs on the
        cloud engine instead of dying at call time with a local 404.
        """
        # Local engine: healthy, but cannot serve cloud-namespaced ids.
        local = mock.MagicMock()
        local.engine_id = "ollama"
        local.health.return_value = True
        local.list_models.return_value = ["qwen2.5:1.5b"]
        local.can_serve.side_effect = lambda m: not m.startswith("openrouter/")

        # Cloud engine: serves the openrouter fallback and answers.
        cloud = mock.MagicMock()
        cloud.engine_id = "cloud"
        cloud.health.return_value = True
        cloud.list_models.return_value = ["openrouter/free"]
        cloud.can_serve.side_effect = lambda m: m.startswith("openrouter/")
        cloud.generate.return_value = {
            "content": "CLOUD-OK",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "openrouter/free",
            "finish_reason": "stop",
        }

        # get_engine: first call (default model) -> local; re-resolve for the
        # cloud fallback model -> cloud.
        def _get_engine(config, key=None, model=None):  # noqa: ANN001
            if model and model.startswith("openrouter/"):
                return ("cloud", cloud)
            return ("ollama", local)

        _register_agents()
        with (
            mock.patch.object(_ask_mod, "get_engine", side_effect=_get_engine),
            mock.patch.object(
                _ask_mod,
                "discover_engines",
                return_value={"ollama": local, "cloud": cloud},
            ),
            mock.patch.object(
                _ask_mod,
                "discover_models",
                return_value={"ollama": ["qwen2.5:1.5b"], "cloud": ["openrouter/free"]},
            ),
            mock.patch.object(_ask_mod, "register_builtin_models"),
            mock.patch.object(_ask_mod, "merge_discovered_models"),
            mock.patch.object(_ask_mod, "TelemetryStore"),
            mock.patch.object(_ask_mod, "load_config") as mock_config,
        ):
            cfg = mock_config.return_value
            cfg.telemetry.enabled = False
            # default_model is configured but NOT present on the local engine.
            cfg.intelligence.default_model = "missing-local-model"
            cfg.intelligence.fallback_model = "openrouter/free"
            cfg.intelligence.preferred_engine = ""
            cfg.intelligence.temperature = 0.7
            cfg.intelligence.max_tokens = 1024
            cfg.agent.context_from_memory = False
            cfg.agent.default_agent = ""
            result = CliRunner().invoke(cli, ["ask", "Hello"])

        assert result.exit_code == 0, result.output
        # The cloud engine (not the local one) must have served the request.
        assert cloud.generate.called
        assert not local.generate.called
        assert cloud.generate.call_args.kwargs["model"] == "openrouter/free"
