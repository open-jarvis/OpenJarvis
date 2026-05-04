"""Tests for openjarvis.cli._first_run.check_and_route."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from openjarvis.cli import _first_run


def _ctx_with_invocation(name: str | None) -> MagicMock:
    ctx = MagicMock()
    ctx.invoked_subcommand = name
    return ctx


def test_passes_through_when_subcommand_present(tmp_openjarvis_home: Path) -> None:
    """If user typed `jarvis ask ...`, guard is a no-op."""
    ctx = _ctx_with_invocation("ask")
    result = _first_run.check_and_route(ctx)
    assert result is None
    ctx.invoke.assert_not_called()


def test_routes_to_chat_when_config_exists(tmp_openjarvis_home: Path) -> None:
    (tmp_openjarvis_home / "config.toml").write_text('[engine]\ndefault = "ollama"\n')
    ctx = _ctx_with_invocation(None)
    _first_run.check_and_route(ctx)
    assert ctx.invoke.called
    invoked_cmd = ctx.invoke.call_args[0][0]
    assert invoked_cmd.name == "chat"


def test_routes_to_init_when_no_config(tmp_openjarvis_home: Path) -> None:
    ctx = _ctx_with_invocation(None)
    _first_run.check_and_route(ctx)
    assert ctx.invoke.called
    invoked_cmd = ctx.invoke.call_args[0][0]
    assert invoked_cmd.name == "init"
    # Cold-path init must run with the from-bare-jarvis flag set.
    assert ctx.invoke.call_args.kwargs.get("from_bare_jarvis") is True


def test_handles_missing_state_dir(tmp_path: Path, monkeypatch) -> None:
    """When ~/.openjarvis doesn't exist at all, route to init."""
    fresh_home = tmp_path / "fresh"
    monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_DIR", fresh_home)
    monkeypatch.setattr(
        "openjarvis.core.config.DEFAULT_CONFIG_PATH", fresh_home / "config.toml"
    )
    ctx = _ctx_with_invocation(None)
    _first_run.check_and_route(ctx)
    invoked_cmd = ctx.invoke.call_args[0][0]
    assert invoked_cmd.name == "init"
