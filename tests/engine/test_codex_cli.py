"""Tests for the Codex CLI engine backend."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.codex_cli import CodexCLIEngine


def test_codex_cli_registered():
    EngineRegistry.register_value("codex_cli", CodexCLIEngine)
    assert EngineRegistry.contains("codex_cli")


def test_codex_cli_health_false_without_command():
    engine = CodexCLIEngine(command="")
    assert engine.health() is False


def test_codex_cli_generate_uses_exec_helper():
    engine = CodexCLIEngine(command="codex")

    with patch(
        "openjarvis.engine.codex_cli._run_codex_exec",
        return_value="Bereit.",
    ) as run:
        result = engine.generate(
            [Message(role=Role.USER, content="Status?")],
            model="gpt-5.5",
        )

    assert result["content"] == "Bereit."
    assert result["model"] == "gpt-5.5"
    assert result["finish_reason"] == "stop"
    run.assert_called_once()
    assert "Status?" in run.call_args.args[0]


def test_codex_cli_generate_requires_command():
    engine = CodexCLIEngine(command="")
    with pytest.raises(EngineConnectionError):
        engine.generate([Message(role=Role.USER, content="Hi")], model="gpt-5.5")


def test_codex_cli_lists_expected_models():
    engine = CodexCLIEngine(command="codex")
    assert "gpt-5.5" in engine.list_models()
