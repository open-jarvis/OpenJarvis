"""Tests for ``jarvis config set`` command."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli


class TestConfigSet:
    def test_set_creates_config_file(self, tmp_path: Path) -> None:
        """config set creates config.toml if it doesn't exist."""
        config_file = tmp_path / "config.toml"
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with mock.patch.dict(os.environ, env):
            result = CliRunner().invoke(
                cli, ["config", "set", "engine.default", "vllm"]
            )
        assert result.exit_code == 0
        assert config_file.exists()
        content = config_file.read_text()
        assert "vllm" in content

    def test_set_engine_ollama_host(self, tmp_path: Path) -> None:
        """config set writes engine.ollama.host correctly."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[engine]\ndefault = "ollama"\n')
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch("openjarvis.cli.config_cmd.httpx"),
        ):
            result = CliRunner().invoke(
                cli,
                ["config", "set", "engine.ollama.host", "http://192.168.1.50:11434"],
            )
        assert result.exit_code == 0
        content = config_file.read_text()
        assert "http://192.168.1.50:11434" in content

    def test_set_preserves_existing_keys(self, tmp_path: Path) -> None:
        """config set preserves other keys in the file."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[engine]\ndefault = "ollama"\n\n'
            "[intelligence]\n"
            'default_model = "qwen2.5:3b"\n'
        )
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with mock.patch.dict(os.environ, env):
            result = CliRunner().invoke(
                cli, ["config", "set", "engine.default", "vllm"]
            )
        assert result.exit_code == 0
        content = config_file.read_text()
        assert "vllm" in content
        assert "qwen2.5:3b" in content

    def test_set_invalid_key_rejected(self, tmp_path: Path) -> None:
        """config set rejects unknown keys."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with mock.patch.dict(os.environ, env):
            result = CliRunner().invoke(
                cli, ["config", "set", "engine.olllama.host", "http://x:1234"]
            )
        assert result.exit_code != 0
        assert "Unknown config key" in result.output

    def test_set_engine_host_probes_reachable(self, tmp_path: Path) -> None:
        """config set probes engine host and reports reachability."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch("openjarvis.cli.config_cmd.httpx") as mock_httpx,
        ):
            mock_httpx.get.return_value = mock.Mock(status_code=200)
            result = CliRunner().invoke(
                cli,
                ["config", "set", "engine.ollama.host", "http://myserver:11434"],
            )
        assert result.exit_code == 0
        assert "Reachable" in result.output

    def test_set_engine_host_probes_unreachable(self, tmp_path: Path) -> None:
        """config set warns when engine host is unreachable, but still writes."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch("openjarvis.cli.config_cmd.httpx") as mock_httpx,
        ):
            mock_httpx.get.side_effect = Exception("Connection refused")
            result = CliRunner().invoke(
                cli,
                ["config", "set", "engine.ollama.host", "http://myserver:11434"],
            )
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "unreachable" in output_lower or "warning" in output_lower
        content = config_file.read_text()
        assert "http://myserver:11434" in content

    def test_set_integer_value(self, tmp_path: Path) -> None:
        """config set coerces integer values."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with mock.patch.dict(os.environ, env):
            result = CliRunner().invoke(
                cli, ["config", "set", "intelligence.max_tokens", "2048"]
            )
        assert result.exit_code == 0
        content = config_file.read_text()
        assert "2048" in content

    def test_set_float_value(self, tmp_path: Path) -> None:
        """config set coerces float values."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with mock.patch.dict(os.environ, env):
            result = CliRunner().invoke(
                cli, ["config", "set", "intelligence.temperature", "0.9"]
            )
        assert result.exit_code == 0
        content = config_file.read_text()
        assert "0.9" in content

    def test_set_missing_args(self) -> None:
        """config set with missing args shows usage error."""
        result = CliRunner().invoke(cli, ["config", "set"])
        assert result.exit_code != 0

    def test_set_shows_confirmation(self, tmp_path: Path) -> None:
        """config set prints a confirmation message."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        env = {"OPENJARVIS_CONFIG": str(config_file)}
        with mock.patch.dict(os.environ, env):
            result = CliRunner().invoke(
                cli, ["config", "set", "engine.default", "vllm"]
            )
        assert result.exit_code == 0
        assert "Set" in result.output
        assert "engine.default" in result.output
