"""Tests for the CLI skeleton."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli


class TestCLI:
    def test_help(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "OpenJarvis" in result.output

    def test_version(self) -> None:
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_ask_requires_query(self) -> None:
        result = CliRunner().invoke(cli, ["ask"])
        assert result.exit_code != 0

    def test_serve_needs_engine(self) -> None:
        """Serve requires a running engine; exits with error when none available."""
        result = CliRunner().invoke(cli, ["serve"])
        # Either exits with error (no engine) or succeeds (deps missing)
        # Both are valid states for testing
        out = result.output.lower()
        assert (
            result.exit_code != 0
            or "not installed" in out
            or "no inference" in out
        )

    def test_model_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["model", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "info" in result.output
        assert "pull" in result.output

    def test_memory_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["memory", "--help"])
        assert result.exit_code == 0
        assert "index" in result.output
        assert "search" in result.output
        assert "stats" in result.output

    def test_telemetry_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["telemetry", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "export" in result.output
        assert "clear" in result.output

    def test_bench_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["bench", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_scheduler_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["scheduler", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "pause" in result.output
        assert "resume" in result.output
        assert "cancel" in result.output

    def test_channel_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["channel", "--help"])
        assert result.exit_code == 0
        assert "send" in result.output
        assert "list" in result.output

    def test_init_creates_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch(
                "openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir
            ),
            mock.patch(
                "openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path
            ),
        ):
            result = CliRunner().invoke(cli, ["init", "--engine", "ollama"])
        assert result.exit_code == 0
        assert config_path.exists()
        content = config_path.read_text()
        assert "[engine]" in content
