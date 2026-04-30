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


def test_kokoro_lang_for_voice_mandarin():
    """Mandarin voice IDs (zf_*, zm_*) map to lang_code='z'."""
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    assert KokoroTTSBackend._lang_for_voice("zf_xiaoxiao") == "z"
    assert KokoroTTSBackend._lang_for_voice("zm_yunxi") == "z"


def test_kokoro_lang_for_voice_english_and_other_languages():
    """Voice prefix detection covers English variants and other languages."""
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    assert KokoroTTSBackend._lang_for_voice("af_heart") == "a"
    assert KokoroTTSBackend._lang_for_voice("am_adam") == "a"
    assert KokoroTTSBackend._lang_for_voice("bf_emma") == "b"
    assert KokoroTTSBackend._lang_for_voice("jf_alpha") == "j"


def test_kokoro_lang_for_voice_unknown_falls_back_to_english():
    """Unknown prefixes fall back to American English (Kokoro's most-stocked
    language) rather than crashing — keeps backward-compat for any
    user-supplied voice ID we haven't catalogued."""
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    assert KokoroTTSBackend._lang_for_voice("") == "a"
    assert KokoroTTSBackend._lang_for_voice("xx_unknown") == "a"


def test_kokoro_available_voices_includes_mandarin_and_english():
    """Voice catalog must list at least one Mandarin voice and preserve
    the original English voices for backward compatibility."""
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    voices = KokoroTTSBackend().available_voices()
    # New Mandarin coverage (the focus of this change)
    for v in ("zf_xiaoxiao", "zf_xiaoyi", "zm_yunxi", "zm_yunjian"):
        assert v in voices, f"Mandarin voice {v} missing from catalog"
    # Backward compat — voices the previous implementation listed
    for v in ("af_heart", "af_bella", "am_adam", "am_michael"):
        assert v in voices, f"Existing voice {v} dropped from catalog"


def test_kokoro_pipeline_cached_per_language(monkeypatch):
    """Each lang_code instantiates one pipeline; same lang reuses the cache."""
    import sys
    import types

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    init_calls = []

    class FakeKPipeline:
        def __init__(self, lang_code):
            init_calls.append(lang_code)

    fake_kokoro = types.SimpleNamespace(KPipeline=FakeKPipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)

    backend = KokoroTTSBackend()
    backend._ensure_pipeline("a")
    backend._ensure_pipeline("z")
    backend._ensure_pipeline("a")  # cache hit — must NOT re-instantiate
    backend._ensure_pipeline("z")  # cache hit

    assert init_calls == ["a", "z"]


def test_kokoro_synthesize_routes_voice_to_correct_language(monkeypatch):
    """synthesize() with a Mandarin voice initializes a Mandarin pipeline
    and tags the result metadata with the resolved lang_code."""
    import sys
    import types

    import numpy as np

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    init_args = []
    call_args = []

    class FakeKPipeline:
        def __init__(self, lang_code):
            init_args.append(lang_code)

        def __call__(self, text, voice, speed):
            call_args.append({"text": text, "voice": voice, "speed": speed})
            yield (None, None, np.zeros(2400, dtype=np.float32))

    fake_kokoro = types.SimpleNamespace(KPipeline=FakeKPipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)

    # ``soundfile`` is a kokoro-runtime dep; stub it so we can test the
    # routing logic without requiring it in the OpenJarvis test env.
    def _fake_sf_write(buf, _samples, _sr, format=None):  # noqa: A002
        buf.write(b"FAKE_AUDIO_BYTES")

    fake_soundfile = types.SimpleNamespace(write=_fake_sf_write)
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)

    backend = KokoroTTSBackend()
    result = backend.synthesize("你好世界", voice_id="zf_xiaoxiao")

    assert init_args == ["z"]
    assert call_args[0]["voice"] == "zf_xiaoxiao"
    assert call_args[0]["text"] == "你好世界"
    assert result.voice_id == "zf_xiaoxiao"
    assert result.metadata["lang_code"] == "z"
    assert result.metadata["backend"] == "kokoro"
    assert result.format == "wav"
    assert len(result.audio) > 0


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
