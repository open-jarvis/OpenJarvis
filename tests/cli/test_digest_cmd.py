"""Tests for `jarvis digest` CLI command."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
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

    play = MagicMock()
    monkeypatch.setattr(digest_mod, "_play_audio", play)
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
    assert play.call_count == int(should_play)
    if should_play:
        play.assert_called_once_with(str(audio_path))
    if text_only:
        assert "Playing audio" not in result.output
        assert "TTS failed" not in result.output
    if fresh:
        jarvis.return_value.__enter__.return_value.ask.assert_called_once_with(
            "Generate my morning digest", agent="morning_digest"
        )
    else:
        jarvis.assert_not_called()


def test_play_audio_falls_back_without_an_external_player(monkeypatch):
    from openjarvis.cli import digest_cmd

    player = MagicMock(side_effect=FileNotFoundError())
    fallback = MagicMock()
    monkeypatch.setattr(digest_cmd.subprocess, "run", player)
    monkeypatch.setattr("openjarvis.speech.voice_io.play_audio_file", fallback)

    digest_cmd._play_audio("digest.mp3")

    assert player.call_count == 4
    fallback.assert_called_once_with("digest.mp3")


def test_play_audio_keeps_a_working_external_player(monkeypatch):
    from openjarvis.cli import digest_cmd

    fallback = MagicMock()
    monkeypatch.setattr(digest_cmd.subprocess, "run", MagicMock())
    monkeypatch.setattr("openjarvis.speech.voice_io.play_audio_file", fallback)
    digest_cmd._play_audio("digest.mp3")
    fallback.assert_not_called()


def test_play_audio_reports_fallback_failure(monkeypatch, caplog):
    from openjarvis.cli import digest_cmd

    monkeypatch.setattr(
        digest_cmd.subprocess, "run", MagicMock(side_effect=FileNotFoundError())
    )
    monkeypatch.setattr(
        "openjarvis.speech.voice_io.play_audio_file",
        MagicMock(side_effect=RuntimeError("no output device")),
    )
    digest_cmd._play_audio("digest.mp3")
    assert "Digest audio playback failed" in caplog.text


@pytest.mark.parametrize("fresh", [False, True])
def test_digest_waits_for_playback_to_finish(tmp_path, monkeypatch, fresh):
    import threading

    from openjarvis.cli import cli, digest_cmd

    audio = tmp_path / "digest.wav"
    audio.write_bytes(b"audio")
    db_path = str(tmp_path / "digest.db")
    with closing(DigestStore(db_path=db_path)) as store:
        store.save(
            DigestArtifact(
                text="Digest playback lifecycle",
                audio_path=audio,
                sections={},
                sources_used=[],
                generated_at=datetime.now(timezone.utc),
                model_used="test",
                voice_used="test",
            )
        )

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    results = []

    def play(path):
        started.set()
        assert release.wait(3)

    monkeypatch.setattr(digest_cmd, "_play_audio", play)
    monkeypatch.setattr("openjarvis.sdk.Jarvis", MagicMock())

    def invoke():
        try:
            args = ["digest", "--db-path", db_path]
            if fresh:
                args.append("--fresh")
            results.append(CliRunner().invoke(cli, args))
        finally:
            finished.set()

    worker = threading.Thread(target=invoke)
    worker.start()
    try:
        assert started.wait(2)
        assert not finished.wait(0.05)
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert len(results) == 1
    assert results[0].exit_code == 0, results[0].output


def test_digest_process_does_not_exit_before_playback_finishes(tmp_path):
    script = textwrap.dedent("""
        from contextlib import closing
        from datetime import datetime, timezone
        import importlib
        from pathlib import Path
        import sys
        import time
        root = Path(sys.argv[1])
        home = root / "home"
        home.mkdir()
        (home / "config.toml").write_text("[analytics]\\nenabled = false\\n")
        audio = root / "digest.wav"
        audio.write_bytes(b"test audio")
        from openjarvis.agents.digest_store import DigestArtifact, DigestStore
        from openjarvis.cli import cli
        module = importlib.import_module("openjarvis.cli.digest_cmd")
        db = str(root / "digest.db")
        with closing(DigestStore(db_path=db)) as store:
            store.save(DigestArtifact(
                text="Digest process lifecycle",
                audio_path=audio,
                sections={},
                sources_used=[],
                generated_at=datetime.now(timezone.utc),
                model_used="test",
                voice_used="test",
            ))
        def play(path):
            time.sleep(0.2)
            (root / "playback-finished").write_text("finished")
        module._play_audio = play
        cli.main(["digest", "--db-path", db], standalone_mode=True)
    """)
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["OPENJARVIS_HOME"] = str(tmp_path / "home")
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "playback-finished").read_text() == "finished"
