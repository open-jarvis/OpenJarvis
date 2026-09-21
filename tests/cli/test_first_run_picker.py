"""Tests for bare ``jarvis`` routing with model picker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.cli._first_run import check_and_route
from openjarvis.cli.chat_cmd import chat as chat_cmd
from openjarvis.cli.init_cmd import init as init_cmd
from openjarvis.core import config as _cfg


@pytest.fixture()
def config_path(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.toml"
    path.write_text("[engine]\ndefault = 'ollama'\n", encoding="utf-8")
    monkeypatch.setattr(_cfg, "DEFAULT_CONFIG_PATH", path)
    return path


def test_check_and_route_enables_picker_on_tty(config_path) -> None:
    ctx = MagicMock()
    ctx.invoked_subcommand = None
    ctx.obj = {}
    with patch("sys.stdin.isatty", return_value=True):
        check_and_route(ctx)
    ctx.invoke.assert_called_once_with(chat_cmd, pick_model=True)


def test_check_and_route_skips_picker_with_env(
    config_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_SKIP_MODEL_PICK", "1")
    ctx = MagicMock()
    ctx.invoked_subcommand = None
    ctx.obj = {}
    with patch("sys.stdin.isatty", return_value=True):
        check_and_route(ctx)
    ctx.invoke.assert_called_once_with(chat_cmd, pick_model=False)


def test_check_and_route_runs_init_without_config(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "no-config.toml"
    monkeypatch.setattr(_cfg, "DEFAULT_CONFIG_PATH", missing)
    ctx = MagicMock()
    ctx.invoked_subcommand = None
    check_and_route(ctx)
    ctx.invoke.assert_called_once_with(init_cmd, from_bare_jarvis=True)
