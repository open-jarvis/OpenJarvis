"""Voice-ID selection for chat TTS.

Voice IDs are not portable between backends. These tests pin the rule that a
configured voice is only ever handed to the backend it belongs to, so a Kokoro
ID like ``bm_george`` can never reach OpenAI or Cartesia on fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

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
