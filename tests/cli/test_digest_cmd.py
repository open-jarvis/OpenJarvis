"""Tests for `jarvis digest` CLI command."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from openjarvis.agents.digest_store import DigestArtifact, DigestStore


def test_digest_command_exists():
    """The digest command is registered on the CLI."""
    from openjarvis.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--help"])
    assert result.exit_code == 0
    assert "digest" in result.output.lower()


def test_digest_displays_cached(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "digest.db")
    store = DigestStore(db_path=db_path)
    store.save(
        DigestArtifact(
            text="# Messages\nYou have 3 emails.\n# Calendar\n2 meetings today.",
            audio_path=Path("/nonexistent/audio.mp3"),
            sections={},
            sources_used=["gmail"],
            generated_at=datetime.now(tz=__import__("datetime").timezone.utc),
            model_used="test",
            voice_used="jarvis",
        )
    )
    store.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--text-only", "--db-path", db_path])
    assert result.exit_code == 0
    assert "3 emails" in result.output


def test_digest_no_cache(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "empty.db")
    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--db-path", db_path])
    assert result.exit_code == 0
    assert "No digest for today" in result.output


@pytest.mark.parametrize("fresh", [False, True])
@pytest.mark.parametrize("text_only", [False, True])
@pytest.mark.parametrize("audio_kind", ["file", "empty", "directory", "missing"])
def test_digest_playback_requires_audio_file_and_audio_enabled(
    tmp_path, monkeypatch, fresh, text_only, audio_kind
):
    import importlib

    from openjarvis.cli import cli

    digest_mod = importlib.import_module("openjarvis.cli.digest_cmd")
    if audio_kind == "empty":
        audio_path = Path("")
    else:
        audio_path = tmp_path / audio_kind
        if audio_kind == "file":
            audio_path.write_bytes(b"audio")
        elif audio_kind == "directory":
            audio_path.mkdir()

    db_path = str(tmp_path / "digest.db")
    with closing(DigestStore(db_path=db_path)) as store:
        store.save(
            DigestArtifact(
                text="Digest regression content",
                audio_path=audio_path,
                sections={},
                sources_used=[],
                generated_at=datetime.now(timezone.utc),
                model_used="test",
                voice_used="test",
            )
        )

    thread = MagicMock()
    monkeypatch.setattr(digest_mod, "threading", SimpleNamespace(Thread=thread))
    jarvis = MagicMock()
    monkeypatch.setattr("openjarvis.sdk.Jarvis", jarvis)
    args = ["digest", "--db-path", db_path]
    if fresh:
        args.append("--fresh")
    if text_only:
        args.append("--text-only")

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    assert "Digest regression content" in result.output
    should_play = not text_only and audio_kind == "file"
    assert thread.call_count == int(should_play)
    assert thread.return_value.start.call_count == int(should_play)
    if text_only:
        assert "Playing audio" not in result.output
        assert "TTS failed" not in result.output
    if fresh:
        jarvis.return_value.__enter__.return_value.ask.assert_called_once_with(
            "Generate my morning digest", agent="morning_digest"
        )
    else:
        jarvis.assert_not_called()
