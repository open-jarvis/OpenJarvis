"""Tests for ``openjarvis.cli.ollama_launch_cmd``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from openjarvis.cli.ollama_launch_cmd import (
    _ALIAS_MAP,
    _ENV_BY_INTEGRATION,
    _resolve_integration,
    _resolve_model,
    launch_group,
)


def test_resolve_integration_normalizes_known_tools():
    assert _resolve_integration("claude") == "claude"
    assert _resolve_integration(" openclaw ") == "openclaw"


def test_resolve_integration_alias_maps():
    assert _resolve_integration("clawdbot") == "openclaw"


def test_resolve_integration_unknown_returns_none():
    assert _resolve_integration("unknown-tool") is None


def test_resolve_model_uses_requested_model():
    assert _resolve_model(requested="qwen3.5:cloud") == "qwen3.5:cloud"


def test_resolve_model_preserves_case():
    assert _resolve_model(requested="Gemma4") == "Gemma4"


def test_env_by_integration_has_required_keys():
    for target in ("claude", "codex", "opencode", "openclaw", "vscode", "pi", "droid"):
        payload = _ENV_BY_INTEGRATION[target]
        common = {
            "OPENAI_BASE_URL",
            "OPENAI_API_KEY",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
        }
        assert set(payload.keys()) <= common
        for value in payload.values():
            assert value


def test_launch_group_has_expected_commands():
    assert "launch" in launch_group.commands
    assert "codex" in launch_group.commands
    assert "opencode" in launch_group.commands


def test_launch_integration_help_shows_usage():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(launch_group, ["launch", "--help"])
    assert result.exit_code == 0
    assert "Integration" in result.output or "usage" in result.output.lower()


def test_config_templates_are_defined():
    from openjarvis.cli.ollama_launch_cmd import _CONFIG_TEMPLATES

    assert "codex" in _CONFIG_TEMPLATES
    assert "opencode" in _CONFIG_TEMPLATES


def test_launch_integration_config_only_writes_and_prints():
    from click.testing import CliRunner

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            launch_group,
            ["launch", "opencode", "--config", "--yes", "--model", "qwen3.5"],
        )
        assert result.exit_code == 0, result.output
        assert "integration" in result.output
        assert "model" in result.output
