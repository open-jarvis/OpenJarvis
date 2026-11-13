"""Latency behaviour of chat voice output.

Replies are spoken sentence by sentence while later sentences are still being
synthesized, and speech models can be warmed up before the first turn.
"""

from __future__ import annotations

from dataclasses import dataclass

from openjarvis.cli._voice_chat import VoiceSession, _split_for_speech, speak
from openjarvis.speech.tts import TTSResult


@dataclass
class _Speech:
    tts_backend: str = "kokoro"
    voice_id: str = "pm_alex"
    voice_speed: float = 0.9


@dataclass
class _Config:
    speech: _Speech


class _Console:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message) -> None:
        self.messages.append(str(message))


class _Backend:
    def __init__(self, backend_id: str = "kokoro", fail_on: str | None = None):
        self.backend_id = backend_id
        self.fail_on = fail_on
        self.spoken: list[tuple[str, dict]] = []

    def synthesize(self, text, **kwargs):
        self.spoken.append((text, kwargs))
        if text == self.fail_on:
            raise RuntimeError("synthesis failed")
        return TTSResult(audio=text.encode(), sample_rate=24000, format="wav")


def _session(monkeypatch, backend) -> VoiceSession:
    session = VoiceSession(config=_Config(speech=_Speech()))
    monkeypatch.setattr(session, "get_tts_backend", lambda: backend)
    return session


def _capture_playback(monkeypatch) -> list[bytes]:
    played: list[bytes] = []
    monkeypatch.setattr(
        "openjarvis.speech.voice_io.play_wav",
        lambda audio, **kwargs: played.append(audio),
    )
    return played


def test_split_merges_short_fragments_into_the_next_sentence():
    text = "Sim, senhor. Já está feito. O relatório foi salvo em Documentos."

    assert _split_for_speech(text) == [
        "Sim, senhor. Já está feito.",
        "O relatório foi salvo em Documentos.",
    ]


def test_split_keeps_text_without_sentence_breaks_whole():
    assert _split_for_speech("First reply") == ["First reply"]
    assert _split_for_speech("") == [""]


def test_speak_plays_every_chunk_in_order(monkeypatch):
    backend = _Backend()
    played = _capture_playback(monkeypatch)
    text = (
        "Bom dia, senhor, tudo em ordem. A reunião foi adiada para amanhã. "
        "Deseja que eu avise os participantes?"
    )

    speak(text, _Console(), _session(monkeypatch, backend))

    chunks = _split_for_speech(text)
    assert len(chunks) == 3
    assert played == [chunk.encode() for chunk in chunks]
    assert all(
        kwargs == {"output_format": "wav", "speed": 0.9, "voice_id": "pm_alex"}
        for _, kwargs in backend.spoken
    )


def test_speak_stops_without_fallback_when_a_later_chunk_fails(monkeypatch):
    backend = _Backend(fail_on="A reunião foi adiada para amanhã.")
    played = _capture_playback(monkeypatch)
    console = _Console()
    session = _session(monkeypatch, backend)
    discarded = []
    monkeypatch.setattr(session, "discard_tts_backend", lambda: discarded.append(1))

    speak(
        "Bom dia, senhor, tudo em ordem. A reunião foi adiada para amanhã. "
        "Deseja que eu avise os participantes?",
        console,
        session,
    )

    assert played == [b"Bom dia, senhor, tudo em ordem."]
    assert discarded == []
    assert any("Voice playback stopped" in message for message in console.messages)


def test_warm_up_loads_stt_model_and_local_tts_voice(monkeypatch):
    loaded = []

    class SttBackend:
        def _ensure_model(self):
            loaded.append("stt")

    backend = _Backend("kokoro")
    session = _session(monkeypatch, backend)
    monkeypatch.setattr(session, "get_stt_backend", lambda: SttBackend())

    session._warm_up()

    assert loaded == ["stt"]
    assert [text for text, _ in backend.spoken] == ["Ok."]
    assert backend.spoken[0][1]["voice_id"] == "pm_alex"


def test_warm_up_never_calls_billed_tts_backends(monkeypatch):
    backend = _Backend("openai_tts")
    session = _session(monkeypatch, backend)
    monkeypatch.setattr(session, "get_stt_backend", lambda: None)

    session._warm_up()

    assert backend.spoken == []
