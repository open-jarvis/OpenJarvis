"""Tests for `jarvis digest` CLI command."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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


def test_play_audio_falls_back_to_sounddevice_without_cli_player(tmp_path, monkeypatch):
    """No CLI player on the platform returns the WAV bytes to in-process playback."""
    from openjarvis.cli import digest_cmd

    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFFfakewavbytes")

    def _no_cli_player(cmd_parts, **kwargs):
        raise FileNotFoundError("no player here")

    monkeypatch.setattr(digest_cmd.subprocess, "run", _no_cli_player)

    played: list[bytes] = []
    monkeypatch.setattr(
        "openjarvis.speech.voice_io.play_wav",
        lambda audio, sample_rate=24000: played.append(audio),
    )

    digest_cmd._play_audio(str(wav))

    assert played == [b"RIFFfakewavbytes"]
