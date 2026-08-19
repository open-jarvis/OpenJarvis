"""Tests for VoiceService's wake-word -> transcribe -> route -> reply state machine.

No real audio hardware is used: fake audio chunks are fed directly into
``_on_audio_chunk`` (the same seam a real ``sounddevice`` callback would
use), with a fake detector/speech backend/agent standing in for the real
things — mirrors ``tests/memory/test_memory_service.py``'s threading-test
idiom (``_wait_until`` polling helper).
"""

from __future__ import annotations

import time

from openjarvis.core.events import EventBus, EventType
from openjarvis.speech.voice_service import VoiceService


def _wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeDetector:
    def __init__(self, trigger_on_call: int = 1) -> None:
        self.calls = 0
        self._trigger_on_call = trigger_on_call

    def process_chunk(self, chunk):
        self.calls += 1
        if self.calls == self._trigger_on_call:
            return "hey_jarvis"
        return None


class FakeTranscriptionResult:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeSpeechBackend:
    def __init__(self, text: str) -> None:
        self._text = text
        self.transcribe_calls = []

    def transcribe(self, audio_bytes, *, format="wav", language=None):
        self.transcribe_calls.append((audio_bytes, format, language))
        return FakeTranscriptionResult(self._text)


class FakeAgent:
    def __init__(self, content: str) -> None:
        self._content = content
        self.run_calls = []

    def run(self, text, **kwargs):
        self.run_calls.append(text)
        from openjarvis.agents._stubs import AgentResult

        return AgentResult(content=self._content)


def _speech_chunk(duration_s: float, sample_rate: int) -> list:
    return [2000] * int(duration_s * sample_rate)


def _silence_chunk(duration_s: float, sample_rate: int) -> list:
    return [0] * int(duration_s * sample_rate)


def _make_service(**overrides):
    sample_rate = 16000
    defaults = dict(
        engine=None,
        model="fake-model",
        speech_backend=FakeSpeechBackend("abra o laboratório científico"),
        detector=FakeDetector(),
        sample_rate=sample_rate,
        silence_timeout_s=0.05,
        tts_backend="nonexistent-tts-backend",
    )
    defaults.update(overrides)
    return VoiceService(
        defaults.pop("engine"),
        defaults.pop("model"),
        defaults.pop("speech_backend"),
        **defaults,
    )


class TestVoiceServiceStateMachine:
    def test_wake_word_to_reply_full_cycle(self):
        bus = EventBus(record_history=True)
        agent = FakeAgent("Abrindo o laboratório científico.")
        svc = _make_service(event_bus=bus, science_lab_agent=agent)
        svc._set_status("listening")

        # Trigger wake word.
        svc._on_audio_chunk([0] * 100)
        assert svc.status()["state"] == "wake_detected"

        # Feed enough "speech" then "silence" to cross both the min-utterance
        # duration and the silence timeout.
        svc._on_audio_chunk(_speech_chunk(0.4, 16000))
        svc._on_audio_chunk(_silence_chunk(0.1, 16000))

        assert _wait_until(lambda: svc.status()["state"] == "listening")

        event_types = [e.event_type for e in bus.history]
        assert EventType.WAKE_WORD_DETECTED in event_types
        assert EventType.VOICE_UTTERANCE_TRANSCRIBED in event_types
        assert EventType.VOICE_INTENT_ROUTED in event_types
        assert EventType.VOICE_REPLY_SPOKEN in event_types

    def test_routes_science_lab_intent_to_science_lab_agent(self):
        agent = FakeAgent("Resultado da análise.")
        svc = _make_service(
            speech_backend=FakeSpeechBackend("analise este material"),
            science_lab_agent=agent,
        )
        svc._set_status("listening")
        svc._on_audio_chunk([0] * 100)
        svc._on_audio_chunk(_speech_chunk(0.4, 16000))
        svc._on_audio_chunk(_silence_chunk(0.1, 16000))
        assert _wait_until(lambda: svc.status()["state"] == "listening")
        assert agent.run_calls == ["analise este material"]

    def test_routes_unmatched_text_to_main_agent(self):
        main_agent = FakeAgent("Resposta de chat.")
        svc = _make_service(
            speech_backend=FakeSpeechBackend("qual é a previsão do tempo?"),
            main_agent=main_agent,
        )
        svc._set_status("listening")
        svc._on_audio_chunk([0] * 100)
        svc._on_audio_chunk(_speech_chunk(0.4, 16000))
        svc._on_audio_chunk(_silence_chunk(0.1, 16000))
        assert _wait_until(lambda: svc.status()["state"] == "listening")
        assert main_agent.run_calls == ["qual é a previsão do tempo?"]

    def test_chunks_ignored_outside_listening_state(self):
        detector = FakeDetector()
        svc = _make_service(detector=detector)
        svc._set_status("transcribing")
        svc._on_audio_chunk([0] * 100)
        assert detector.calls == 0
        assert svc.status()["state"] == "transcribing"

    def test_status_reflects_last_utterance(self):
        svc = _make_service(speech_backend=FakeSpeechBackend("salve esse projeto"))
        svc._set_status("listening")
        svc._on_audio_chunk([0] * 100)
        svc._on_audio_chunk(_speech_chunk(0.4, 16000))
        svc._on_audio_chunk(_silence_chunk(0.1, 16000))
        assert _wait_until(
            lambda: svc.status().get("last_utterance") == "salve esse projeto"
        )

    def test_empty_transcription_returns_to_listening_without_reply(self):
        bus = EventBus(record_history=True)
        svc = _make_service(speech_backend=FakeSpeechBackend(""), event_bus=bus)
        svc._set_status("listening")
        svc._on_audio_chunk([0] * 100)
        svc._on_audio_chunk(_speech_chunk(0.4, 16000))
        svc._on_audio_chunk(_silence_chunk(0.1, 16000))
        assert _wait_until(lambda: svc.status()["state"] == "listening")
        event_types = [e.event_type for e in bus.history]
        assert EventType.VOICE_REPLY_SPOKEN not in event_types
