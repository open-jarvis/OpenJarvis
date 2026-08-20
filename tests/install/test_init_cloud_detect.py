"""Tests for init's cloud auto-detect and from-bare-jarvis flag."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from openjarvis.cli.init_cmd import init


def _clear_keys(monkeypatch) -> None:
    for k in (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)


def test_init_accepts_from_bare_jarvis_flag(
    tmp_openjarvis_home: Path, monkeypatch
) -> None:
    """The --from-bare-jarvis flag exists and suppresses the launch-chat prompt."""
    _clear_keys(monkeypatch)
    runner = CliRunner()
    # Use --engine + --no-download + --no-scan to skip interactive paths
    # that would otherwise hang on a non-TTY runner.
    result = runner.invoke(
        init,
        ["--from-bare-jarvis", "--engine", "ollama", "--no-download", "--no-scan"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    # When --from-bare-jarvis, we expect NOT to see a "launch chat" affordance.
    assert "Launch chat" not in result.output


def test_init_proposes_cloud_when_key_in_env(
    tmp_openjarvis_home: Path, monkeypatch
) -> None:
    """When ANTHROPIC_API_KEY is set, init mentions cloud / anthropic."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    runner = CliRunner()
    result = runner.invoke(
        init,
        ["--from-bare-jarvis", "--engine", "ollama", "--no-download", "--no-scan"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "anthropic" in result.output.lower() or "cloud" in result.output.lower()


def test_init_from_bare_jarvis_skips_engine_prompt(
    tmp_openjarvis_home: Path, monkeypatch
) -> None:
    """--from-bare-jarvis must not hang on the engine-selection prompt
    even when --engine is not provided."""
    _clear_keys(monkeypatch)
    runner = CliRunner()
    # Note: NO --engine flag passed. Without the gating fix this would hang.
    result = runner.invoke(
        init,
        ["--from-bare-jarvis", "--no-download", "--no-scan"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
