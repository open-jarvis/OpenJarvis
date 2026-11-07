"""Tests for friday_ai.cli._first_run.check_and_route."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from friday_ai.cli import _first_run


def _ctx_with_invocation(name: str | None) -> MagicMock:
    ctx = MagicMock()
    ctx.invoked_subcommand = name
    return ctx


def test_passes_through_when_subcommand_present(tmp_friday_ai_home: Path) -> None:
    """If user typed `friday ask ...`, guard is a no-op."""
    ctx = _ctx_with_invocation("ask")
    result = _first_run.check_and_route(ctx)
    assert result is None
    ctx.invoke.assert_not_called()


def test_routes_to_chat_when_config_exists(tmp_friday_ai_home: Path) -> None:
    (tmp_friday_ai_home / "config.toml").write_text('[engine]\ndefault = "ollama"\n')
    ctx = _ctx_with_invocation(None)
    _first_run.check_and_route(ctx)
    assert ctx.invoke.called
    invoked_cmd = ctx.invoke.call_args[0][0]
    assert invoked_cmd.name == "chat"


def test_routes_to_init_when_no_config(tmp_friday_ai_home: Path) -> None:
    ctx = _ctx_with_invocation(None)
    _first_run.check_and_route(ctx)
    assert ctx.invoke.called
    invoked_cmd = ctx.invoke.call_args[0][0]
    assert invoked_cmd.name == "init"
    # Cold-path init must run with the from-bare-friday flag set.
    assert ctx.invoke.call_args.kwargs.get("from_bare_friday") is True


def test_handles_missing_state_dir(tmp_path: Path, monkeypatch) -> None:
    """When ~/.friday_ai doesn't exist at all, route to init."""
    fresh_home = tmp_path / "fresh"
    monkeypatch.setattr("friday_ai.core.config.DEFAULT_CONFIG_DIR", fresh_home)
    monkeypatch.setattr(
        "friday_ai.core.config.DEFAULT_CONFIG_PATH", fresh_home / "config.toml"
    )
    ctx = _ctx_with_invocation(None)
    _first_run.check_and_route(ctx)
    invoked_cmd = ctx.invoke.call_args[0][0]
    assert invoked_cmd.name == "init"


def test_root_group_invokes_guard_on_bare_friday(
    tmp_friday_ai_home: Path, monkeypatch
) -> None:
    """End-to-end: bare `friday` invocation calls the first-run guard.

    We monkeypatch check_and_route to a recorder so we can verify it was
    called with a click.Context whose invoked_subcommand is None.
    """
    from click.testing import CliRunner

    calls: list[object] = []

    def _recorder(ctx) -> None:
        calls.append(ctx.invoked_subcommand)

    monkeypatch.setattr("friday_ai.cli._first_run.check_and_route", _recorder)

    from friday_ai.cli import cli

    runner = CliRunner()
    runner.invoke(cli, [], catch_exceptions=False)
    assert calls == [None], f"expected one call with None subcommand, got {calls}"


def test_root_group_does_not_invoke_guard_on_subcommand(
    tmp_friday_ai_home: Path, monkeypatch
) -> None:
    """When a subcommand is given, the guard must NOT fire."""
    from click.testing import CliRunner

    calls: list[object] = []

    def _recorder(ctx) -> None:
        calls.append(ctx.invoked_subcommand)

    monkeypatch.setattr("friday_ai.cli._first_run.check_and_route", _recorder)

    from friday_ai.cli import cli

    runner = CliRunner()
    runner.invoke(cli, ["--help"], catch_exceptions=False)
    assert calls == [], f"expected no guard calls, got {calls}"
