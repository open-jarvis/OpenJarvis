"""Tests for the ``jarvis config`` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli


class TestConfigCmd:
    """Test cases for the jarvis config CLI group."""

    def test_config_group_help(self) -> None:
        """Test that the config group help displays correctly."""
        result = CliRunner().invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "config" in result.output.lower()

    def test_config_show_help(self) -> None:
        """Test that the config show help displays correctly."""
        result = CliRunner().invoke(cli, ["config", "show", "--help"])
        assert result.exit_code == 0
        assert "show" in result.output.lower()

    def test_config_show_loaded_help(self) -> None:
        """Test that the config show loaded help displays correctly."""
        result = CliRunner().invoke(cli, ["config", "show", "loaded", "--help"])
        assert result.exit_code == 0
        assert "loaded" in result.output.lower()

    def test_config_show_toml_help(self) -> None:
        """Test that the config show toml help displays correctly."""
        result = CliRunner().invoke(cli, ["config", "show", "toml", "--help"])
        assert result.exit_code == 0
        assert "toml" in result.output.lower()

    def test_config_show_json_help(self) -> None:
        """Test that the config show json help displays correctly."""
        result = CliRunner().invoke(cli, ["config", "show", "json", "--help"])
        assert result.exit_code == 0
        assert "json" in result.output.lower()

    def test_config_show_hardware_help(self) -> None:
        """Test that the config show hardware help displays correctly."""
        result = CliRunner().invoke(cli, ["config", "show", "hardware", "--help"])
        assert result.exit_code == 0
        assert "hardware" in result.output.lower()

    def test_config_show_loaded_displays_config(self, tmp_path: Path) -> None:
        """Test that config show loaded displays the configuration."""
        # Create a temporary config file
        config_file = tmp_path / "test_config.toml"
        config_file.write_text(
            """
[engine]
default = "ollama"

[intelligence]
default_model = "test-model"
temperature = 0.7
max_tokens = 1024

[agent]
default_agent = "simple"
max_turns = 5
"""
        )

        result = CliRunner().invoke(
            cli, ["config", "show", "loaded", "--path", str(config_file)]
        )

        assert result.exit_code == 0
        assert "ollama" in result.output
        assert "test-model" in result.output

    def test_config_show_loaded_json_output(self, tmp_path: Path) -> None:
        """Test that config show loaded --json outputs valid JSON."""
        # Create a temporary config file
        config_file = tmp_path / "test_config.toml"
        config_file.write_text(
            """
[engine]
default = "ollama"

[intelligence]
default_model = "test-model"
temperature = 0.7
"""
        )

        result = CliRunner().invoke(
            cli, ["config", "show", "loaded", "--path", str(config_file), "--json"]
        )

        assert result.exit_code == 0
        # Try to parse the output as JSON (may have prefix lines)
        # Find the JSON part by looking for the opening brace
        json_start = result.output.find("{")
        assert json_start >= 0, f"Could not find JSON in output: {result.output}"
        try:
            json_data = json.loads(result.output[json_start:])
            assert "engine" in json_data
            assert json_data["engine"]["default"] == "ollama"
        except json.JSONDecodeError:
            pytest.fail(f"Output is not valid JSON: {result.output}")

    def test_config_show_toml_displays_raw_content(self, tmp_path: Path) -> None:
        """Test that config show toml displays the raw TOML content."""
        # Create a temporary config file
        config_file = tmp_path / "test_config.toml"
        config_file.write_text('[engine]\ndefault = "ollama"\n')

        result = CliRunner().invoke(
            cli, ["config", "show", "toml", "--path", str(config_file)]
        )

        assert result.exit_code == 0
        assert "[engine]" in result.output
        assert "ollama" in result.output

    def test_config_show_json_displays_parsed_content(self, tmp_path: Path) -> None:
        """Test that config show json displays parsed TOML as JSON."""
        # Create a temporary config file
        config_file = tmp_path / "test_config.toml"
        config_file.write_text('[engine]\ndefault = "ollama"\n')

        result = CliRunner().invoke(
            cli, ["config", "show", "json", "--path", str(config_file)]
        )

        assert result.exit_code == 0
        # The output should be valid JSON (may have prefix lines)
        json_start = result.output.find("{")
        assert json_start >= 0, f"Could not find JSON in output: {result.output}"
        try:
            json_data = json.loads(result.output[json_start:])
            assert json_data["engine"]["default"] == "ollama"
        except json.JSONDecodeError:
            pytest.fail(f"Output is not valid JSON: {result.output}")

    def test_config_show_hardware_displays_info(self) -> None:
        """Test that config show hardware displays hardware information."""
        result = CliRunner().invoke(cli, ["config", "show", "hardware"])
        assert result.exit_code == 0
        # Should display hardware-related content
        output = result.output.lower()
        assert "hardware" in output or "cpu" in output or "ram" in output

    def test_config_show_default_to_loaded(self, tmp_path: Path) -> None:
        """Test that config show (no subcommand) defaults to loaded."""
        # Create a temporary config file
        config_file = tmp_path / "test_config.toml"
        config_file.write_text('[engine]\ndefault = "ollama"\n')

        result = CliRunner().invoke(cli, ["config", "show", "--path", str(config_file)])

        assert result.exit_code == 0
        # Default behavior should show loaded config
        assert "ollama" in result.output

    def test_config_show_no_config_file(self, tmp_path: Path) -> None:
        """Test that config show handles missing config file gracefully."""
        # Create a path for a non-existent config file
        config_file = tmp_path / "nonexistent_config.toml"

        result = CliRunner().invoke(
            cli, ["config", "show", "toml", "--path", str(config_file)]
        )

        # Should exit 0 and show a message about missing config
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "config" in result.output.lower()

    def test_config_show_path_option(self, tmp_path: Path) -> None:
        """Test that the --path option works for all subcommands."""
        # Create a custom config file
        custom_config = tmp_path / "custom.toml"
        custom_config.write_text('[engine]\ndefault = "custom-engine"\n')

        # Test various subcommands with custom path
        result = CliRunner().invoke(
            cli, ["config", "show", "toml", "--path", str(custom_config)]
        )
        assert result.exit_code == 0
        assert "custom-engine" in result.output

        result = CliRunner().invoke(
            cli, ["config", "show", "json", "--path", str(custom_config)]
        )
        assert result.exit_code == 0
        assert "custom-engine" in result.output

    def test_config_show_invalid_subcommand(self) -> None:
        """Test that an invalid subcommand shows an error."""
        result = CliRunner().invoke(cli, ["config", "show", "invalid_subcommand_xyz"])
        # Should show error about unknown command
        assert result.exit_code != 0
        assert "no such" in result.output.lower() or "unknown" in result.output.lower()

    def test_config_subcommands_not_available_standalone(self) -> None:
        """Test that config subcommands are not available directly under config."""
        # These should not be available as direct children of config
        result = CliRunner().invoke(cli, ["config", "loaded"])
        assert result.exit_code != 0
        assert "no such" in result.output.lower() or "unknown" in result.output.lower()
