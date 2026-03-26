"""Tests for model resolution fallback chain in jarvis ask."""

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


class TestAskModelResolution:
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
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0

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
            result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0
