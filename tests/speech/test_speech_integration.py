"""Integration tests for speech STT/TTS round-trip."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def ffmpeg_path():
    path = shutil.which("ffmpeg")
    if not path:
        pytest.skip("ffmpeg not installed")
    return path


def test_edge_tts_synthesize_returns_audio():
    pytest.importorskip("edge_tts")
    from openjarvis.speech.edge_tts import EdgeTTSBackend

    backend = EdgeTTSBackend()
    assert backend.health() is True
    result = backend.synthesize("Hello, this is a speech integration test.")
    assert len(result.audio) > 1000
    assert result.format == "mp3"


def test_edge_tts_audio_transcribes_to_english(ffmpeg_path):
    pytest.importorskip("edge_tts")
    pytest.importorskip("faster_whisper")
    from openjarvis.speech.edge_tts import EdgeTTSBackend
    from openjarvis.speech.faster_whisper import FasterWhisperBackend

    phrase = "The quick brown fox jumps over the lazy dog."
    mp3 = EdgeTTSBackend().synthesize(phrase).audio

    with tempfile.TemporaryDirectory() as tmp:
        mp3_path = Path(tmp) / "sample.mp3"
        webm_path = Path(tmp) / "sample.webm"
        mp3_path.write_bytes(mp3)
        subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-i",
                str(mp3_path),
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                str(webm_path),
            ],
            capture_output=True,
            check=True,
        )
        webm = webm_path.read_bytes()

    stt = FasterWhisperBackend(model_size="small", device="cpu", compute_type="int8")
    result = stt.transcribe(webm, format="webm", language="en")
    assert result.text
    assert "fox" in result.text.lower() or "quick" in result.text.lower()
