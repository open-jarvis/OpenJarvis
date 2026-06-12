"""Tests for TTS backend infrastructure."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSResult

# ---------------------------------------------------------------------------
# TTSResult tests
# ---------------------------------------------------------------------------


def test_tts_result_dataclass():
    result = TTSResult(
        audio=b"fake-audio-bytes",
        format="mp3",
        duration_seconds=3.5,
        voice_id="jarvis-v1",
    )
    assert result.audio == b"fake-audio-bytes"
    assert result.format == "mp3"
    assert result.duration_seconds == 3.5


def test_tts_result_save(tmp_path):
    result = TTSResult(audio=b"fake-mp3-data", format="mp3")
    out = result.save(tmp_path / "test.mp3")
    assert out.exists()
    assert out.read_bytes() == b"fake-mp3-data"


# ---------------------------------------------------------------------------
# Cartesia backend tests
# ---------------------------------------------------------------------------


def test_cartesia_registered():
    from openjarvis.speech.cartesia_tts import CartesiaTTSBackend

    TTSRegistry.register_value("cartesia", CartesiaTTSBackend)
    assert TTSRegistry.contains("cartesia")


def test_cartesia_synthesize():
    from openjarvis.speech.cartesia_tts import CartesiaTTSBackend

    backend = CartesiaTTSBackend(api_key="fake-key")

    with patch(
        "openjarvis.speech.cartesia_tts._cartesia_synthesize",
        return_value=b"fake-audio-mp3-bytes",
    ):
        result = backend.synthesize("Hello world", voice_id="test-voice")

    assert result.audio == b"fake-audio-mp3-bytes"
    assert result.format == "mp3"
    assert result.voice_id == "test-voice"


# ---------------------------------------------------------------------------
# Kokoro backend tests
# ---------------------------------------------------------------------------


def test_kokoro_registered():
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    TTSRegistry.register_value("kokoro", KokoroTTSBackend)
    assert TTSRegistry.contains("kokoro")


def test_kokoro_health_false_without_package():
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    # Without kokoro installed, health returns False
    assert backend.health() is False


# ---------------------------------------------------------------------------
# OpenAI TTS backend tests
# ---------------------------------------------------------------------------


def test_openai_tts_registered():
    from openjarvis.speech.openai_tts import OpenAITTSBackend

    TTSRegistry.register_value("openai_tts", OpenAITTSBackend)
    assert TTSRegistry.contains("openai_tts")


def test_openai_tts_synthesize():
    from openjarvis.speech.openai_tts import OpenAITTSBackend

    backend = OpenAITTSBackend(api_key="fake-key")

    with patch(
        "openjarvis.speech.openai_tts._openai_tts_request",
        return_value=b"fake-openai-audio",
    ):
        result = backend.synthesize("Hello", voice_id="nova")

    assert result.audio == b"fake-openai-audio"
    assert result.voice_id == "nova"


# ---------------------------------------------------------------------------
# Streaming infrastructure tests
# ---------------------------------------------------------------------------


class _StubTTS:
    """Minimal TTS backend exercising the base ``synthesize_stream`` default."""

    backend_id = "stub"

    def synthesize(self, text, *, voice_id="", speed=1.0, output_format="mp3"):
        return TTSResult(audio=b"full-clip", format="mp3", voice_id=voice_id)

    def available_voices(self):
        return []

    def health(self):
        return True


def test_base_synthesize_stream_yields_full_audio():
    from openjarvis.speech.tts import TTSBackend

    # Borrow the unbound base method so a stub that only implements
    # synthesize() still streams its full clip as a single chunk.
    chunks = list(TTSBackend.synthesize_stream(_StubTTS(), "hello"))
    assert b"".join(chunks) == b"full-clip"


def test_base_synthesize_stream_skips_empty_audio():
    from openjarvis.speech.tts import TTSBackend, TTSResult as _R

    class _Empty(_StubTTS):
        def synthesize(self, text, *, voice_id="", speed=1.0, output_format="mp3"):
            return _R(audio=b"", format="mp3")

    chunks = list(TTSBackend.synthesize_stream(_Empty(), "hello"))
    assert chunks == []


def test_edge_tts_overrides_synthesize_stream():
    from openjarvis.speech.edge_tts import EdgeTTSBackend
    from openjarvis.speech.tts import TTSBackend

    # edge_tts produces audio incrementally, so it must not use the buffered
    # base implementation.
    assert EdgeTTSBackend.synthesize_stream is not TTSBackend.synthesize_stream
