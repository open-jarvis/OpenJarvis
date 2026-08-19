"""VoiceService — local wake-word listening loop running inside `jarvis serve`.

Copies ``memory/service.py``'s ``MemoryService`` lifecycle shape (idempotent
``start()``/``stop()``, daemon thread) but is driven by a continuous
``sounddevice.InputStream`` callback instead of a work queue. State machine::

    listening -> (wake word detected) -> wake_detected (capturing utterance,
    energy-based VAD with a silence timeout) -> transcribing (batch STT via
    the existing SpeechBackend, unchanged) -> routes the transcript through
    IntentRouter -> dispatches to ScienceLabAgent / the main chat agent ->
    replying (TTS + playback) -> back to listening.

Runs entirely in the Python backend (OS-level mic capture via `sounddevice`,
not browser ``getUserMedia``) so it is unaffected by whether any Tauri
window is open or focused — the frontend only polls :meth:`status`, it never
captures audio itself. Fully optional: :func:`build_voice_service` returns
``None`` (never raises) when disabled or when its dependencies
(`openwakeword`, `sounddevice`) are not installed, so `jarvis serve` never
crashes because of this module.
"""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventBus, EventType
from openjarvis.speech.intent_router import (
    ACTION_ANALYZE_MATERIAL,
    ACTION_COMPARE_MATERIALS,
    ACTION_OPEN_SCIENCE_LAB,
    ACTION_SAVE_PROJECT,
    ACTION_SIMULATE_MIXTURE,
    IntentRouter,
)
from openjarvis.speech.wakeword import WakeWordDetector

logger = logging.getLogger(__name__)

# Energy (mean absolute int16 amplitude) below which a chunk is "silence".
# Heuristic default — quiet-room noise floor is typically well under 100;
# speech is typically in the low thousands.
_SILENCE_ENERGY_THRESHOLD = 150.0
_MIN_UTTERANCE_SECONDS = 0.3


def _play_audio_file(audio_path: str) -> None:
    """Play a saved audio file via whatever system player is available.

    Duplicates the small player-probing loop from ``cli/digest_cmd.py``
    rather than importing it — the CLI layer depends on `speech/`, not the
    other way around.
    """
    players = ["ffplay -nodisp -autoexit", "aplay", "afplay", "paplay"]
    for player in players:
        cmd_parts = player.split() + [audio_path]
        try:
            subprocess.run(
                cmd_parts,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue


class VoiceService:
    """Background wake-word listener + intent router + spoken-reply loop."""

    def __init__(
        self,
        engine: Any,
        model: str,
        speech_backend: Any,
        *,
        science_lab_agent: Optional[Any] = None,
        main_agent: Optional[Any] = None,
        event_bus: Optional[EventBus] = None,
        wake_word: str = "hey_jarvis",
        threshold: float = 0.5,
        device_index: int = -1,
        sample_rate: int = 16000,
        silence_timeout_s: float = 1.2,
        stt_language: str = "",
        tts_backend: str = "cartesia",
        voice_id: str = "",
        voice_speed: float = 1.0,
        detector: Optional[WakeWordDetector] = None,
        intent_router: Optional[IntentRouter] = None,
    ) -> None:
        self._engine = engine
        self._model = model
        self._speech_backend = speech_backend
        self._science_lab_agent = science_lab_agent
        self._main_agent = main_agent
        self._event_bus = event_bus
        self._wake_word = wake_word
        self._device_index = device_index
        self._sample_rate = sample_rate
        self._silence_timeout_s = silence_timeout_s
        self._stt_language = stt_language or None
        self._tts_backend_key = tts_backend
        self._voice_id = voice_id
        self._voice_speed = voice_speed

        self._detector = detector or WakeWordDetector(wake_word, threshold)
        self._intent_router = intent_router or IntentRouter()

        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stream: Optional[Any] = None
        self._worker_lock = threading.Lock()

        self._status_lock = threading.Lock()
        self._status: Dict[str, Any] = {
            "state": "idle",
            "last_utterance": "",
            "updated_at": time.time(),
        }

        # Utterance-capture state (touched only from the audio callback
        # thread, so no lock needed for these two fields specifically).
        self._capture_buffer: List[Any] = []
        self._silence_accum_s: float = 0.0

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Start the background mic-capture stream (idempotent)."""
        if self._running.is_set():
            return
        import sounddevice as sd  # type: ignore[import-not-found]

        self._running.set()
        self._set_status("listening")
        blocksize = max(1, int(self._sample_rate * 0.08))  # ~80ms frames
        device = self._device_index if self._device_index >= 0 else None
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            blocksize=blocksize,
            device=device,
            callback=self._sd_callback,
        )
        self._stream.start()
        logger.debug("Voice service started (wake word: %r)", self._wake_word)

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the mic-capture stream (idempotent)."""
        if not self._running.is_set():
            return
        self._running.clear()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                logger.debug("Voice service stream teardown failed", exc_info=True)
            self._stream = None
        self._set_status("idle")
        logger.debug("Voice service stopped")

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def status(self) -> Dict[str, Any]:
        with self._status_lock:
            return dict(self._status)

    def _set_status(self, state: str, **extra: Any) -> None:
        with self._status_lock:
            self._status = {
                "state": state,
                "last_utterance": self._status.get("last_utterance", ""),
                "updated_at": time.time(),
                **extra,
            }

    # -- audio callback ---------------------------------------------------

    def _sd_callback(
        self, indata: Any, frames: int, time_info: Any, status: Any
    ) -> None:
        chunk = indata[:, 0] if getattr(indata, "ndim", 1) > 1 else indata
        self._on_audio_chunk(chunk)

    def _on_audio_chunk(self, chunk: Any) -> None:
        """Process one mono int16 PCM chunk. Called directly by tests."""
        state = self.status()["state"]

        if state == "listening":
            try:
                detected = self._detector.process_chunk(chunk)
            except Exception:  # noqa: BLE001 - a bad frame must not kill capture
                logger.debug("Wake-word detection failed on a chunk", exc_info=True)
                return
            if detected:
                self._capture_buffer = []
                self._silence_accum_s = 0.0
                self._set_status("wake_detected")
                if self._event_bus is not None:
                    self._event_bus.publish(
                        EventType.WAKE_WORD_DETECTED, {"wake_word": detected}
                    )
            return

        if state == "wake_detected":
            self._capture_buffer.append(chunk)
            chunk_duration_s = len(chunk) / float(self._sample_rate)
            energy = _mean_abs(chunk)
            if energy < _SILENCE_ENERGY_THRESHOLD:
                self._silence_accum_s += chunk_duration_s
            else:
                self._silence_accum_s = 0.0

            captured_s = sum(len(c) for c in self._capture_buffer) / float(
                self._sample_rate
            )
            if (
                self._silence_accum_s >= self._silence_timeout_s
                and captured_s >= _MIN_UTTERANCE_SECONDS
            ):
                buffer = self._capture_buffer
                self._capture_buffer = []
                self._set_status("transcribing")
                with self._worker_lock:
                    threading.Thread(
                        target=self._finish_utterance,
                        args=(buffer,),
                        daemon=True,
                        name="voice-service-utterance",
                    ).start()
            return

        # transcribing / replying / idle: drop chunks (avoid re-triggering
        # on our own TTS playback and avoid racing the worker thread).

    # -- utterance processing (runs off the audio callback thread) -------

    def _finish_utterance(self, chunks: List[Any]) -> None:
        try:
            audio_bytes = _chunks_to_wav_bytes(chunks, self._sample_rate)
            result = self._speech_backend.transcribe(
                audio_bytes, format="wav", language=self._stt_language
            )
            text = (result.text or "").strip()
            self._set_status("transcribing", last_utterance=text)
            if self._event_bus is not None:
                self._event_bus.publish(
                    EventType.VOICE_UTTERANCE_TRANSCRIBED, {"text": text}
                )

            if not text:
                self._set_status("listening")
                return

            intent = self._intent_router.route(text)
            if self._event_bus is not None:
                self._event_bus.publish(
                    EventType.VOICE_INTENT_ROUTED, {"action": intent.action}
                )

            reply_text = self._handle_intent(intent.action, text)

            self._set_status("replying", last_utterance=text)
            self._speak(reply_text)
            if self._event_bus is not None:
                self._event_bus.publish(
                    EventType.VOICE_REPLY_SPOKEN, {"text": reply_text}
                )
        except Exception:  # noqa: BLE001 - a bad utterance must not kill the service
            logger.debug("Voice utterance processing failed", exc_info=True)
        finally:
            self._set_status("listening")

    def _handle_intent(self, action: str, text: str) -> str:
        if action == ACTION_OPEN_SCIENCE_LAB:
            return "Abrindo o laboratório científico."
        if action in (
            ACTION_ANALYZE_MATERIAL,
            ACTION_COMPARE_MATERIALS,
            ACTION_SIMULATE_MIXTURE,
        ):
            if self._science_lab_agent is not None:
                result = self._science_lab_agent.run(text)
                return result.content
            return "O módulo de laboratório científico não está disponível no momento."
        if action == ACTION_SAVE_PROJECT:
            return (
                "Para salvar um projeto, diga o nome depois de 'salvar projeto' "
                "ou use a página do Science Lab."
            )
        # ACTION_CHAT_FALLBACK
        if self._main_agent is not None:
            result = self._main_agent.run(text)
            return result.content
        return "Desculpe, não há um agente de conversa configurado."

    def _speak(self, text: str) -> None:
        if not text:
            return
        try:
            import openjarvis.speech  # noqa: F401 - trigger backend registration
            from openjarvis.core.registry import TTSRegistry

            if not TTSRegistry.contains(self._tts_backend_key):
                logger.debug("TTS backend %r not available", self._tts_backend_key)
                return
            backend_cls = TTSRegistry.get(self._tts_backend_key)
            backend = backend_cls()
            result = backend.synthesize(
                text, voice_id=self._voice_id, speed=self._voice_speed
            )
            with tempfile.TemporaryDirectory(prefix="jarvis-voice-") as tmp_dir:
                audio_path = Path(tmp_dir) / f"reply.{result.format or 'mp3'}"
                result.save(audio_path)
                _play_audio_file(str(audio_path))
        except Exception:  # noqa: BLE001 - a broken TTS path must not kill the service
            logger.debug("Voice reply synthesis/playback failed", exc_info=True)


def _mean_abs(chunk: Any) -> float:
    total = 0.0
    n = 0
    for v in chunk:
        total += abs(float(v))
        n += 1
    return total / n if n else 0.0


def _chunks_to_wav_bytes(chunks: List[Any], sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        for chunk in chunks:
            wf.writeframes(bytes(_to_int16_bytes(chunk)))
    return buf.getvalue()


def _to_int16_bytes(chunk: Any) -> bytes:
    try:
        import numpy as np  # type: ignore[import-not-found]

        arr = np.asarray(chunk, dtype=np.int16)
        return arr.tobytes()
    except ImportError:
        import struct

        return b"".join(struct.pack("<h", int(v)) for v in chunk)


def build_voice_service(
    config: Any,
    engine: Any,
    default_model: str,
    speech_backend: Any,
    *,
    science_lab_agent: Optional[Any] = None,
    main_agent: Optional[Any] = None,
    event_bus: Optional[EventBus] = None,
) -> Optional[VoiceService]:
    """Build a :class:`VoiceService` from config, or ``None`` if unavailable.

    Returns ``None`` (never raises) when ``config.voice.enabled`` is false,
    no speech backend is configured, or the optional `openwakeword` /
    `sounddevice` dependencies aren't installed — matching
    ``build_memory_service``'s "return None, caller checks" contract.
    """
    voice_cfg = getattr(config, "voice", None)
    if voice_cfg is None or not getattr(voice_cfg, "enabled", False):
        return None
    if speech_backend is None:
        logger.debug("Voice service disabled: no speech (STT) backend configured")
        return None
    try:
        import openwakeword  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError:
        logger.debug(
            "Voice service disabled: install the 'speech-wakeword' extra "
            "(openwakeword, sounddevice) to enable the wake-word listener"
        )
        return None

    return VoiceService(
        engine,
        default_model,
        speech_backend,
        science_lab_agent=science_lab_agent,
        main_agent=main_agent,
        event_bus=event_bus,
        wake_word=voice_cfg.wake_word,
        threshold=voice_cfg.threshold,
        device_index=voice_cfg.device_index,
        sample_rate=voice_cfg.sample_rate,
        silence_timeout_s=voice_cfg.silence_timeout_s,
        stt_language=voice_cfg.stt_language,
        tts_backend=voice_cfg.tts_backend,
        voice_id=voice_cfg.voice_id,
        voice_speed=voice_cfg.voice_speed,
    )


__all__ = ["VoiceService", "build_voice_service"]
