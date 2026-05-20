"""Tests for model resolution fallback chain in jarvis ask.

Contract (updated 2026-05): when ``--agent`` is omitted, ``jarvis ask`` now
respects ``config.agent.default_agent`` and routes through the agent path.
These tests exercise the direct-to-engine path by explicitly disabling the
default agent via the mocked config — that's the canonical way to force the
direct path now.
"""

from __future__ import annotations

import importlib
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli

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


def _patch_engine(engine):
    """Return context managers that patch engine discovery to use our mock."""
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


def _build_direct_mode_config(mock_config) -> mock.MagicMock:
    """Wire a mock config that forces direct-to-engine mode (no agent)."""
    cfg = mock_config.return_value
    cfg.telemetry.enabled = False
    cfg.intelligence.default_model = "test-model"
    cfg.intelligence.fallback_model = ""
    cfg.intelligence.preferred_engine = "mock"
    cfg.intelligence.temperature = 0.7
    cfg.intelligence.max_tokens = 1024
    cfg.agent.default_agent = ""  # disable agent → direct mode
    cfg.agent.context_from_memory = False
    cfg.agent.tools = []
    cfg.agent.max_turns = 5
    cfg.tools.enabled = []
    cfg.memory.default_backend = "sqlite"
    cfg.memory.context_top_k = 3
    cfg.memory.context_min_score = 0.0
    cfg.memory.context_max_tokens = 1024
    return cfg


class TestAskModelResolution:
    def test_default_model_from_config(self) -> None:
        """When no -m flag, uses config.intelligence.default_model."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            mock.patch.object(_ask_mod, "load_config") as mock_config,
        ):
            _build_direct_mode_config(mock_config)
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0, result.output
        assert "Hello!" in result.output

    def test_explicit_model_flag(self) -> None:
        """The -m flag directly selects a model, bypassing fallback chain."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            mock.patch.object(_ask_mod, "load_config") as mock_config,
        ):
            _build_direct_mode_config(mock_config)
            result = CliRunner().invoke(
                cli,
                ["ask", "-m", "test-model", "Hello"],
            )
        assert result.exit_code == 0, result.output
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
            cfg = _build_direct_mode_config(mock_config)
            cfg.intelligence.default_model = ""
            cfg.intelligence.fallback_model = ""
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0, result.output

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
            cfg = _build_direct_mode_config(mock_config)
            cfg.intelligence.default_model = ""
            cfg.intelligence.fallback_model = "fallback-model"
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0, result.output


class TestAskAgentDefault:
    """When --agent is omitted, fall back to config.agent.default_agent."""

    def test_default_agent_from_config_invoked(self) -> None:
        """If config.agent.default_agent is set, ask routes through _run_agent."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            mock.patch.object(_ask_mod, "load_config") as mock_config,
            mock.patch.object(_ask_mod, "_run_agent") as mock_run,
        ):
            cfg = _build_direct_mode_config(mock_config)
            cfg.agent.default_agent = "simple"
            mock_run.return_value = mock.MagicMock(
                content="agent ok", turns=1, tool_results=[]
            )
            result = CliRunner().invoke(cli, ["ask", "hi"])
        assert result.exit_code == 0, result.output
        assert mock_run.called
        assert mock_run.call_args.args[0] == "simple"

    def test_explicit_agent_flag_wins(self) -> None:
        """--agent overrides the default_agent fallback."""
        engine = _mock_engine()
        patches = _patch_engine(engine)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            mock.patch.object(_ask_mod, "load_config") as mock_config,
            mock.patch.object(_ask_mod, "_run_agent") as mock_run,
        ):
            cfg = _build_direct_mode_config(mock_config)
            cfg.agent.default_agent = "simple"
            mock_run.return_value = mock.MagicMock(
                content="ok", turns=1, tool_results=[]
            )
            result = CliRunner().invoke(cli, ["ask", "-a", "orchestrator", "hi"])
        assert result.exit_code == 0, result.output
        assert mock_run.called
        assert mock_run.call_args.args[0] == "orchestrator"
