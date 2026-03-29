"""Microphone listener with energy-based Voice Activity Detection (VAD).

Records audio until silence is detected after speech begins.
Requires: sounddevice, numpy
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

import numpy as np

from openjarvis.voice._stubs import AudioChunk

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False
    sd = None  # type: ignore[assignment]


# ── constants ──────────────────────────────────────────────────────────────────
SAMPLE_RATE = 16_000   # Hz  (Whisper expects 16 kHz)
CHANNELS = 1
DTYPE = "int16"
CHUNK_FRAMES = 512     # ~32 ms per callback at 16 kHz
ENERGY_THRESHOLD = 300  # RMS threshold; tune per environment
SILENCE_TIMEOUT = 1.2  # seconds of silence to end utterance
MAX_RECORD_SECONDS = 30


class MicrophoneListener:
    """Streams mic audio and records a single utterance via VAD.

    Usage
    -----
    listener = MicrophoneListener()
    audio_bytes = listener.record_utterance()   # blocks; returns WAV-compatible PCM
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        energy_threshold: int = ENERGY_THRESHOLD,
        silence_timeout: float = SILENCE_TIMEOUT,
        max_seconds: float = MAX_RECORD_SECONDS,
    ) -> None:
        if not _SD_AVAILABLE:
            raise ImportError(
                "sounddevice is not installed. Run: uv pip install sounddevice numpy"
            )
        self._sample_rate = sample_rate
        self._energy_threshold = energy_threshold
        self._silence_timeout = silence_timeout
        self._max_seconds = max_seconds
        self._cancel_event = threading.Event()

    # ── public ─────────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Signal the current recording to abort."""
        self._cancel_event.set()

    def record_utterance(self) -> Optional[bytes]:
        """Record until silence follows speech, or max_seconds hit.

        Returns raw 16-bit PCM bytes at SAMPLE_RATE, or None if cancelled.
        """
        self._cancel_event.clear()
        audio_q: queue.Queue[np.ndarray] = queue.Queue()

        def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
            if status:
                logger.debug("sounddevice status: %s", status)
            audio_q.put(indata.copy())

        frames_collected: list[np.ndarray] = []
        speech_started = False
        last_speech_time = 0.0
        start_time = time.monotonic()

        with sd.InputStream(
            samplerate=self._sample_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_FRAMES,
            callback=_callback,
        ):
            while not self._cancel_event.is_set():
                now = time.monotonic()
                if now - start_time > self._max_seconds:
                    logger.debug("max record time reached")
                    break

                try:
                    chunk = audio_q.get(timeout=0.05)
                except queue.Empty:
                    continue

                rms = int(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

                if rms > self._energy_threshold:
                    if not speech_started:
                        logger.debug("speech started (rms=%d)", rms)
                    speech_started = True
                    last_speech_time = time.monotonic()

                if speech_started:
                    frames_collected.append(chunk)
                    # end of utterance: silence after speech
                    if time.monotonic() - last_speech_time > self._silence_timeout:
                        logger.debug("silence detected — utterance complete")
                        break

        if self._cancel_event.is_set() or not frames_collected:
            return None

        audio_array = np.concatenate(frames_collected, axis=0)
        return audio_array.astype(np.int16).tobytes()

    def stream_chunks(self, chunk_callback) -> None:  # type: ignore[type-arg]
        """Continuously feed raw chunks to ``chunk_callback(AudioChunk)``
        until ``cancel()`` is called. Used by wake word detector."""
        self._cancel_event.clear()
        audio_q: queue.Queue[np.ndarray] = queue.Queue()

        def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
            if status:
                logger.debug("sounddevice status: %s", status)
            audio_q.put(indata.copy())

        with sd.InputStream(
            samplerate=self._sample_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_FRAMES,
            callback=_callback,
        ):
            while not self._cancel_event.is_set():
                try:
                    chunk = audio_q.get(timeout=0.05)
                except queue.Empty:
                    continue
                chunk_callback(
                    AudioChunk(
                        data=chunk.astype(np.int16).tobytes(),
                        sample_rate=self._sample_rate,
                    )
                )


__all__ = ["MicrophoneListener", "SAMPLE_RATE"]
