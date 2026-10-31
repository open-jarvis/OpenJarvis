"""Voice-ID selection for chat TTS.

Voice IDs are not portable between backends. These tests pin the rule that a
configured voice is only ever handed to the backend it belongs to, so a Kokoro
ID like ``bm_george`` can never reach OpenAI or Cartesia on fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from openjarvis.cli._voice_chat import _BACKEND_DEFAULT_VOICE, VoiceSession


@dataclass
class _Speech:
    tts_backend: str = "kokoro"
    voice_id: str = "bm_george"
    voice_speed: float = 1.0


@dataclass
class _Config:
    speech: _Speech


class _Backend:
    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id


def _session(**kwargs) -> VoiceSession:
    return VoiceSession(config=_Config(speech=_Speech(**kwargs)))


def test_configured_voice_used_for_its_own_backend():
    voice_id, speed = _session().voice_for_backend(_Backend("kokoro"))
    assert voice_id == "bm_george"
    assert speed == 1.0


@pytest.mark.parametrize("other", ["openai_tts", "cartesia", "unknown"])
def test_kokoro_voice_never_leaks_to_other_backends(other):
    voice_id, _ = _session().voice_for_backend(_Backend(other))
    assert voice_id != "bm_george"
    assert voice_id == _BACKEND_DEFAULT_VOICE.get(other, "")


def test_openai_fallback_gets_a_voice_openai_accepts():
    from openjarvis.speech.openai_tts import OpenAITTSBackend

    voice_id, _ = _session().voice_for_backend(_Backend("openai_tts"))
    assert voice_id in OpenAITTSBackend.__dict__["available_voices"](
        OpenAITTSBackend.__new__(OpenAITTSBackend)
    )


def test_cartesia_voice_routes_back_to_cartesia_only():
    session = _session(tts_backend="cartesia", voice_id="a-cartesia-uuid")
    assert session.voice_for_backend(_Backend("cartesia"))[0] == "a-cartesia-uuid"
    # ...and must not be handed to Kokoro, which would mis-map its lang code.
    assert session.voice_for_backend(_Backend("kokoro"))[0] == "bm_george"


def test_preload_tts_warms_the_configured_voice(monkeypatch):
    calls: list = []

    class _Preloadable(_Backend):
        def preload(self, voice_id: str = "") -> None:
            calls.append(voice_id)

    session = _session(tts_backend="pocket", voice_id="estelle")
    monkeypatch.setattr(session, "get_tts_backend", lambda: _Preloadable("pocket"))
    session.preload_tts()
    assert calls == ["estelle"]


def test_preload_tts_never_raises(monkeypatch):
    session = _session()

    def _boom():
        raise RuntimeError("no backend")

    monkeypatch.setattr(session, "get_tts_backend", _boom)
    session.preload_tts()  # must not propagate into the chat thread


def test_concurrent_backend_resolution_instantiates_once(monkeypatch):
    import threading
    import time

    created: list = []

    def _slow_get_tts_backend(preferred, attempted=None):
        time.sleep(0.02)
        created.append(preferred)
        return _Backend(preferred)

    monkeypatch.setattr(
        "openjarvis.speech._tts_discovery.get_tts_backend", _slow_get_tts_backend
    )
    session = _session()
    threads = [threading.Thread(target=session.get_tts_backend) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert created == ["kokoro"]


def test_preload_loads_turn_detector_then_stt_then_tts(monkeypatch):
    order: list[str] = []
    session = _session()
    for name in ("preload_turn_detector", "preload_stt", "preload_tts"):
        monkeypatch.setattr(session, name, lambda n=name: order.append(n))
    session.preload()
    assert order == ["preload_turn_detector", "preload_stt", "preload_tts"]


def test_concurrent_stt_resolution_loads_one_model(monkeypatch):
    import threading
    import time

    created: list = []

    def _slow_get_speech_backend(config):
        time.sleep(0.02)
        created.append(config)
        return object()

    monkeypatch.setattr(
        "openjarvis.speech._discovery.get_speech_backend", _slow_get_speech_backend
    )
    session = _session()
    threads = [threading.Thread(target=session.get_stt_backend) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(created) == 1
    assert session.stt_ready


def test_preload_stt_never_raises(monkeypatch):
    session = _session()

    def _boom():
        raise RuntimeError("no stt")

    monkeypatch.setattr(session, "get_stt_backend", _boom)
    session.preload_stt()


def test_preload_turn_detector_uses_configured_model_and_never_raises(monkeypatch):
    seen: list[str] = []

    def _load(path=""):
        seen.append(path)
        raise RuntimeError("onnxruntime exploded")

    monkeypatch.setattr("openjarvis.speech.turn_detection.load_turn_models", _load)
    session = VoiceSession(
        config=SimpleNamespace(speech=SimpleNamespace(turn_model=" C:/st.onnx "))
    )
    session.preload_turn_detector()
    assert seen == ["C:/st.onnx"]


def test_zero_speed_is_not_silently_rewritten():
    assert _session(voice_speed=0.0).get_voice_preferences()[2] == 0.0


def test_warning_emitted_once_per_backend():
    printed: list[str] = []

    class _Console:
        def print(self, msg):
            printed.append(str(msg))

    session, console = _session(), _Console()
    for _ in range(3):
        session.voice_for_backend(_Backend("openai_tts"), console)
    assert len(printed) == 1


@pytest.mark.parametrize("preferred", ["kokoro", "openai_tts", "cartesia"])
def test_configured_backend_is_tried_before_healthy_fallbacks(monkeypatch, preferred):
    import openjarvis.speech  # noqa: F401
    from openjarvis.core.registry import TTSRegistry

    checked = []

    class HealthyBackend(_Backend):
        def health(self):
            checked.append(self.backend_id)
            return True

    monkeypatch.setattr(TTSRegistry, "contains", lambda key: True)
    monkeypatch.setattr(TTSRegistry, "get", lambda key: lambda: HealthyBackend(key))
    session = _session(tts_backend=preferred, voice_id="chosen-voice")

    selected = session.get_tts_backend()

    assert selected.backend_id == preferred
    assert session.get_tts_backend() is selected
    assert checked == [preferred]
    assert session.voice_for_backend(selected) == ("chosen-voice", 1.0)


def test_synthesis_failure_falls_back_without_retrying_or_leaking_voice(monkeypatch):
    import openjarvis.speech  # noqa: F401
    from openjarvis.cli._voice_chat import speak
    from openjarvis.core.registry import TTSRegistry
    from openjarvis.speech.tts import TTSResult

    checked, spoken, played = [], [], []

    class Backend(_Backend):
        def health(self):
            checked.append(self.backend_id)
            return True

        def synthesize(self, text, **kwargs):
            spoken.append((self.backend_id, kwargs["voice_id"]))
            if self.backend_id == "openai_tts":
                raise RuntimeError("provider unavailable")
            return TTSResult(audio=b"wav", sample_rate=24000, format="wav")

    class Console:
        def print(self, message):
            pass

    monkeypatch.setattr(TTSRegistry, "contains", lambda key: True)
    monkeypatch.setattr(TTSRegistry, "get", lambda key: lambda: Backend(key))
    monkeypatch.setattr(
        "openjarvis.speech.voice_io.play_wav",
        lambda audio, **kwargs: played.append(audio),
    )
    session = _session(tts_backend="openai_tts", voice_id="nova")

    speak("First reply", Console(), session)
    speak("Second reply", Console(), session)

    assert checked == ["openai_tts", "kokoro"]
    assert spoken == [
        ("openai_tts", "nova"),
        ("kokoro", "bm_george"),
        ("kokoro", "bm_george"),
    ]
    assert played == [b"wav", b"wav"]
