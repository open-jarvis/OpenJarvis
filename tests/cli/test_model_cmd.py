"""Tests for ``jarvis model`` subcommands."""

from __future__ import annotations

import importlib
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.config import JarvisConfig

# Import the actual module (not the Click group attribute)
_model_mod = importlib.import_module("openjarvis.cli.model")


def _mock_engine():
    """Create a mock engine with list_models and health."""
    engine = mock.MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["model-a", "model-b"]
    return engine


class TestModelList:
    def test_list_from_mock_engine(self, monkeypatch) -> None:
        cfg = JarvisConfig()
        monkeypatch.setattr(_model_mod, "load_config", lambda: cfg)
        fake = _mock_engine()
        monkeypatch.setattr(
            _model_mod,
            "discover_engines",
            lambda c: [("mock", fake)],
        )
        monkeypatch.setattr(
            _model_mod,
            "discover_models",
            lambda e: {"mock": ["model-a", "model-b"]},
        )
        result = CliRunner().invoke(cli, ["model", "list"])
        assert result.exit_code == 0
        assert "model-a" in result.output

    def test_no_engines_message(self, monkeypatch) -> None:
        cfg = JarvisConfig()
        monkeypatch.setattr(_model_mod, "load_config", lambda: cfg)
        monkeypatch.setattr(_model_mod, "discover_engines", lambda c: [])
        result = CliRunner().invoke(cli, ["model", "list"])
        assert result.exit_code == 0
        assert "No inference engines" in result.output


class TestModelInfo:
    def test_info_known_model(self, monkeypatch) -> None:
        cfg = JarvisConfig()
        monkeypatch.setattr(_model_mod, "load_config", lambda: cfg)
        monkeypatch.setattr(_model_mod, "discover_engines", lambda c: [])
        monkeypatch.setattr(_model_mod, "discover_models", lambda e: {})
        result = CliRunner().invoke(cli, ["model", "info", "qwen3:8b"])
        assert result.exit_code == 0
        assert "Qwen3 8B" in result.output

    def test_unknown_model_not_found(self, monkeypatch) -> None:
        cfg = JarvisConfig()
        monkeypatch.setattr(_model_mod, "load_config", lambda: cfg)
        monkeypatch.setattr(_model_mod, "discover_engines", lambda c: [])
        monkeypatch.setattr(_model_mod, "discover_models", lambda e: {})
        result = CliRunner().invoke(cli, ["model", "info", "nonexistent-model"])
        assert result.exit_code != 0
