"""End-to-end tests for ``jarvis ask``."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.config import JarvisConfig

# Import the actual module (not the Click command attribute)
_ask_mod = importlib.import_module("openjarvis.cli.ask")


def _mock_engine_response():
    """Return a mock engine that generates a fixed response."""
    return {
        "content": "The answer is 4.",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        "model": "test-model",
        "finish_reason": "stop",
    }


def _patch_ask(monkeypatch, tmp_path, *, engine_result=None, no_engine=False):
    """Set up common mocks for ask tests."""
    cfg = JarvisConfig()
    cfg.telemetry.db_path = str(tmp_path / "telemetry.db")

    monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)

    if no_engine:
        monkeypatch.setattr(_ask_mod, "get_engine", lambda *a, **kw: None)
    else:
        fake_engine = mock.MagicMock()
        fake_engine.engine_id = "mock"
        fake_engine.health.return_value = True
        fake_engine.generate.return_value = engine_result or _mock_engine_response()
        fake_engine.list_models.return_value = ["test-model"]
        monkeypatch.setattr(
            _ask_mod,
            "get_engine",
            lambda *a, **kw: ("mock", fake_engine),
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_engines",
            lambda c: [("mock", fake_engine)],
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_models",
            lambda e: {"mock": ["test-model"]},
        )


class TestAskCommand:
    def test_basic_response(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["ask", "What is 2+2?"])
        assert result.exit_code == 0
        assert "The answer is 4" in result.output

    def test_no_engine_error(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path, no_engine=True)
        result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code != 0

    def test_model_override(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["ask", "-m", "custom-model", "Hello"])
        assert result.exit_code == 0

    def test_json_output(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["ask", "--json", "Hello"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "content" in data

    def test_telemetry_recorded(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        CliRunner().invoke(cli, ["ask", "Hello"])
        db_path = tmp_path / "telemetry.db"
        assert db_path.exists()
