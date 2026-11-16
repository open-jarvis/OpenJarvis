"""Terminal answers, unattended init, and persisted runtime analytics choices."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import tomllib
from click.testing import CliRunner

from openjarvis.cli import _analytics_consent
from openjarvis.cli.init_cmd import init
from openjarvis.core.config import load_config


class TerminalInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def use_input(monkeypatch, stream: io.StringIO) -> None:
    original = _analytics_consent.click.get_text_stream
    monkeypatch.setattr(
        _analytics_consent.click,
        "get_text_stream",
        lambda name, *args, **kwargs: (
            stream if name == "stdin" else original(name, *args, **kwargs)
        ),
    )


@pytest.mark.parametrize(
    ("answer", "enabled"),
    [
        ("\n", True),
        ("y\n", True),
        ("YES\n", True),
        ("n\n", False),
        ("no\n", False),
        ("", False),
        ("invalid\nn\n", False),
    ],
)
def test_terminal_choice(monkeypatch, capsys, answer: str, enabled: bool) -> None:
    stream = TerminalInput(answer)
    use_input(monkeypatch, stream)
    assert _analytics_consent.ask_analytics_consent() is enabled
    assert "Press Enter or Y to consent, or N to decline" in capsys.readouterr().err


def test_redirected_input_never_consents(monkeypatch) -> None:
    stream = io.StringIO("\n")
    use_input(monkeypatch, stream)
    assert _analytics_consent.ask_analytics_consent() is False
    assert stream.tell() == 0


def test_cancelled_prompt_never_consents(monkeypatch) -> None:
    class CancelledInput(TerminalInput):
        def readline(self, *args) -> str:
            raise KeyboardInterrupt

    use_input(monkeypatch, CancelledInput())
    assert _analytics_consent.ask_analytics_consent() is False


@pytest.mark.parametrize("flag", [None, "--analytics", "--no-analytics"])
def test_init_persists_flag_or_default(
    tmp_openjarvis_home: Path, flag: str | None
) -> None:
    args = ["--engine", "ollama", "--no-download", "--no-scan"]
    if flag:
        args.append(flag)
    result = CliRunner().invoke(init, args)
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_openjarvis_home / "config.toml")
    assert cfg.analytics.enabled is (flag == "--analytics")
    assert not (tmp_openjarvis_home / "anon_id").exists()


@pytest.mark.parametrize(("answer", "enabled"), [("\n", True), ("N\n", False)])
def test_init_persists_interactive_choice(
    tmp_openjarvis_home: Path, monkeypatch, answer: str, enabled: bool
) -> None:
    stream = TerminalInput(answer)
    use_input(monkeypatch, stream)
    result = CliRunner().invoke(
        init, ["--engine", "ollama", "--no-download", "--no-scan"]
    )
    assert result.exit_code == 0, result.output
    data = tomllib.loads((tmp_openjarvis_home / "config.toml").read_text())
    assert data["analytics"]["enabled"] is enabled
    assert load_config(tmp_openjarvis_home / "config.toml").analytics.enabled is enabled


def test_supplied_config_is_preserved_without_a_new_choice(monkeypatch) -> None:
    content = '# Keep this comment\n[engine]\ndefault = "ollama"\n'
    use_input(monkeypatch, io.StringIO())
    assert (
        _analytics_consent.apply_analytics_choice(content, None, prompt=True) == content
    )


def test_decline_replaces_existing_enabled_value_without_losing_settings() -> None:
    content = "# Keep this comment\n[analytics]\nenabled = true\nflush_at_size = 7\n"
    result = _analytics_consent.apply_analytics_choice(content, False, prompt=False)
    data = tomllib.loads(result)
    assert data["analytics"] == {
        "enabled": False,
        "flush_at_size": 7,
        "choice_recorded": True,
    }
    assert "# Keep this comment" in result


def test_prompt_discloses_configured_destination(monkeypatch, capsys) -> None:
    use_input(monkeypatch, TerminalInput("n\n"))
    content = '[analytics]\nhost = "https://analytics.example.org"\n'
    result = _analytics_consent.apply_analytics_choice(content, None, prompt=True)
    assert "https://analytics.example.org" in capsys.readouterr().err
    assert tomllib.loads(result)["analytics"]["enabled"] is False
