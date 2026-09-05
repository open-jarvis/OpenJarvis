"""Tests for the Piper TTS backend."""

from __future__ import annotations

import io
import wave
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.piper_tts import PiperTTSBackend


def _wav_bytes(sample_rate: int = 22050, frames: int = 2205) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


@pytest.fixture
def fake_voice():
    """A PiperVoice stand-in that writes a real WAV through synthesize_wav."""
    voice = MagicMock()
    voice.config.sample_rate = 22050

    def _synthesize_wav(text, wav_file, syn_config=None, **kwargs):
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 2205)

    voice.synthesize_wav.side_effect = _synthesize_wav
    return voice


def test_piper_registered_on_import():
    """The decorator wires the backend into the registry at import time.

    conftest clears every registry before each test, so re-run the module's
    import side effect rather than relying on collection-time registration.
    """
    import importlib

    import openjarvis.speech.piper_tts as module

    importlib.reload(module)

    assert TTSRegistry.contains("piper")
    assert TTSRegistry.get("piper") is module.PiperTTSBackend


def test_synthesize_returns_wav(fake_voice, tmp_path):
    backend = PiperTTSBackend(voice_dir=tmp_path)

    with patch.object(backend, "_ensure_voice", return_value=fake_voice):
        result = backend.synthesize("Guten Morgen", voice_id="de_DE-thorsten-medium")

    assert result.format == "wav"
    assert result.voice_id == "de_DE-thorsten-medium"
    assert result.sample_rate == 22050
    assert result.audio.startswith(b"RIFF")
    assert result.duration_seconds == pytest.approx(0.1, abs=0.01)
    assert result.metadata["backend"] == "piper"


def test_speed_maps_to_reciprocal_length_scale(fake_voice, tmp_path):
    """Piper scales duration, so a 2x speed request is a 0.5 length_scale."""
    backend = PiperTTSBackend(voice_dir=tmp_path)

    with patch.object(backend, "_ensure_voice", return_value=fake_voice):
        backend.synthesize("Test", voice_id="de_DE-thorsten-medium", speed=2.0)

    syn_config = fake_voice.synthesize_wav.call_args[0][2]
    assert syn_config.length_scale == pytest.approx(0.5)


def test_zero_speed_falls_back_to_normal(fake_voice, tmp_path):
    backend = PiperTTSBackend(voice_dir=tmp_path)

    with patch.object(backend, "_ensure_voice", return_value=fake_voice):
        backend.synthesize("Test", speed=0.0)

    syn_config = fake_voice.synthesize_wav.call_args[0][2]
    assert syn_config.length_scale == pytest.approx(1.0)


def test_non_wav_format_rejected(tmp_path):
    backend = PiperTTSBackend(voice_dir=tmp_path)

    with pytest.raises(ValueError, match="WAV only"):
        backend.synthesize("Test", output_format="mp3")


def test_missing_package_raises_actionable_error(tmp_path):
    backend = PiperTTSBackend(voice_dir=tmp_path)

    with patch.dict("sys.modules", {"piper": None}):
        with pytest.raises(RuntimeError, match="voice-piper"):
            backend._ensure_voice("de_DE-thorsten-medium")


def test_voice_cache_is_bounded(tmp_path):
    """Loading more voices than the LRU holds evicts the oldest."""
    backend = PiperTTSBackend(voice_dir=tmp_path)
    for name in ("a", "b", "c", "d"):
        (tmp_path / f"{name}.onnx").write_bytes(b"")

    with patch("piper.PiperVoice") as piper_voice:
        piper_voice.load.side_effect = lambda path: MagicMock(name=str(path))
        with patch.dict("sys.modules", {"piper": MagicMock(PiperVoice=piper_voice)}):
            for name in ("a", "b", "c", "d"):
                backend._ensure_voice(name)

    assert len(backend._voices) == 3
    assert "a" not in backend._voices


def test_available_voices_falls_back_to_local(tmp_path):
    """An unreachable catalog degrades to the voices already on disk."""
    backend = PiperTTSBackend(voice_dir=tmp_path)
    (tmp_path / "de_DE-thorsten-medium.onnx").write_bytes(b"")
    (tmp_path / "en_US-lessac-medium.onnx").write_bytes(b"")

    with patch("httpx.get", side_effect=OSError("offline")):
        voices = backend.available_voices()

    assert voices == ["de_DE-thorsten-medium", "en_US-lessac-medium"]


def test_available_voices_reads_catalog(tmp_path):
    backend = PiperTTSBackend(voice_dir=tmp_path)
    resp = MagicMock()
    resp.json.return_value = {"en_US-lessac-medium": {}, "de_DE-thorsten-medium": {}}

    with patch("httpx.get", return_value=resp) as get:
        voices = backend.available_voices()
        backend.available_voices()  # cached, no second request

    assert voices == ["de_DE-thorsten-medium", "en_US-lessac-medium"]
    assert get.call_count == 1


def test_health_without_package(tmp_path):
    backend = PiperTTSBackend(voice_dir=tmp_path)

    with patch.dict("sys.modules", {"piper": None}):
        assert backend.health() is False
