"""Tests for the jarvis _bootstrap hidden CLI command."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from click.testing import CliRunner

from openjarvis.cli import cli


def test_bootstrap_command_writes_config(
    tmp_openjarvis_home: Path, monkeypatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "_bootstrap",
            "--write-config",
            "--engine",
            "ollama",
            "--model",
            "qwen3.5:2b",
        ],
    )
    assert result.exit_code == 0, result.output
    cfg = tmp_openjarvis_home / "config.toml"
    assert cfg.exists()
    data = tomllib.loads(cfg.read_text())
    assert data["engine"]["default"] == "ollama"
    assert data["intelligence"]["default_model"] == "qwen3.5:2b"


def test_bootstrap_command_uses_cloud_key_when_present(
    tmp_openjarvis_home: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "_bootstrap",
            "--write-config",
            "--prefer-cloud-when-available",
            "--engine",
            "ollama",
            "--model",
            "qwen3.5:2b",
        ],
    )
    assert result.exit_code == 0, result.output
    data = tomllib.loads((tmp_openjarvis_home / "config.toml").read_text())
    # When --prefer-cloud-when-available is set and a key was found,
    # we override engine to cloud.
    assert data["engine"]["default"] == "cloud"
    assert data["intelligence"]["provider"] == "anthropic"


def test_bootstrap_command_is_hidden_from_help(
    tmp_openjarvis_home: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "_bootstrap" not in result.output
