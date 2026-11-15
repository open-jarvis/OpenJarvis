"""Regression tests for no-cloud, local-only Jarvis voice selection."""
from __future__ import annotations

import io
import wave
from unittest.mock import Mock, patch

from openjarvis.speech.jarvis_local_tts import JarvisLocalTTSBackend
from openjarvis.speech._tts_discovery import get_tts_backend


def _wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"\0\0" * 2205)
    return output.getvalue()


def test_jarvis_bridge_ready():
    response = Mock()
    response.json.return_value = {"ready": True}
    with patch("openjarvis.speech.jarvis_local_tts.httpx.get", return_value=response):
        assert JarvisLocalTTSBackend().health()


def test_jarvis_synthesis_wav():
    reply = Mock()
    reply.content = _wav()
    reply.headers = {"X-Jarvis-Voice-Backend": "Piper"}
    with patch("openjarvis.speech.jarvis_local_tts.httpx.post", return_value=reply):
        result = JarvisLocalTTSBackend().synthesize("Good day, sir.")
    assert result.format == "wav"
    assert result.sample_rate == 22050
    assert abs(result.duration_seconds - 0.1) < 0.001
    assert result.metadata["engine"] == "Piper"


def test_corrupt_wav_rejected():
    reply = Mock(content=b"bad audio", headers={})
    with patch("openjarvis.speech.jarvis_local_tts.httpx.post", return_value=reply):
        try:
            JarvisLocalTTSBackend().synthesize("Hello")
        except RuntimeError as exc:
            assert "invalid WAV" in str(exc)
        else:
            raise AssertionError("Invalid audio accepted")


def test_jarvis_local_never_falls_back_to_paid_provider():
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    with patch.object(JarvisLocalTTSBackend, "health", return_value=False), \
            patch.object(KokoroTTSBackend, "health", return_value=False):
        attempted = set()
        assert get_tts_backend("jarvis_local", attempted=attempted) is None
        assert attempted == {"jarvis_local", "kokoro"}
