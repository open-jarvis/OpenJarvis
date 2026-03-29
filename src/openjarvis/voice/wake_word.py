"""Wake word detection.

Primary: openwakeword (open-source ONNX, no API key needed).
Fallback: energy spike + keyword match via STT (if openwakeword not installed).

Install openwakeword:
    uv pip install openwakeword
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

import numpy as np

from openjarvis.voice._stubs import AudioChunk, WakeWordDetector, WakeWordResult

logger = logging.getLogger(__name__)

try:
    from openwakeword.model import Model as OWWModel
    _OWW_AVAILABLE = True
except ImportError:
    _OWW_AVAILABLE = False
    OWWModel = None  # type: ignore[assignment, misc]


# ── openwakeword backend ───────────────────────────────────────────────────────

class OpenWakeWordDetector(WakeWordDetector):
    """Uses openwakeword to detect 'hey jarvis' (or a custom word)."""

    # Shipped models: hey_jarvis, alexa, hey_mycroft, etc.
    # Pass a path to a custom .onnx to load your own.
    DEFAULT_WORDS = ["hey_jarvis"]

    def __init__(
        self,
        wake_words: Optional[list[str]] = None,
        threshold: float = 0.5,
        inference_framework: str = "onnx",
    ) -> None:
        if not _OWW_AVAILABLE:
            raise ImportError(
                "openwakeword not installed. Run: uv pip install openwakeword"
            )
        self._words = wake_words or self.DEFAULT_WORDS
        self._threshold = threshold
        self._model = OWWModel(
            wakeword_models=self._words,
            inference_framework=inference_framework,
        )

    def process_chunk(self, chunk: AudioChunk) -> Optional[WakeWordResult]:
        audio_int16 = np.frombuffer(chunk.data, dtype=np.int16)
        predictions = self._model.predict(audio_int16)
        for word, score in predictions.items():
            if score >= self._threshold:
                logger.info("Wake word detected: %s (%.2f)", word, score)
                return WakeWordResult(word=word, confidence=float(score))
        return None

    def reset(self) -> None:
        # Clear openwakeword internal buffer
        self._model.reset()


# ── energy-based fallback ──────────────────────────────────────────────────────

class EnergyWakeWordDetector(WakeWordDetector):
    """Simple energy-spike detector — fires on loud enough sound above threshold.

    Not truly a wake-word detector, but a useful press-to-talk substitute when
    openwakeword is not available.  Combine with a short STT check if needed.
    """

    def __init__(self, energy_threshold: int = 800, consecutive_chunks: int = 3) -> None:
        self._threshold = energy_threshold
        self._needed = consecutive_chunks
        self._count = 0

    def process_chunk(self, chunk: AudioChunk) -> Optional[WakeWordResult]:
        arr = np.frombuffer(chunk.data, dtype=np.int16).astype(np.float32)
        rms = int(np.sqrt(np.mean(arr ** 2)))
        if rms > self._threshold:
            self._count += 1
            if self._count >= self._needed:
                self._count = 0
                return WakeWordResult(word="energy_spike", confidence=1.0)
        else:
            self._count = 0
        return None

    def reset(self) -> None:
        self._count = 0


# ── background detection thread ───────────────────────────────────────────────

class WakeWordListener:
    """Runs wake word detection in a background thread.

    Usage
    -----
    listener = WakeWordListener()
    listener.start()
    # blocks until a wake word fires:
    result = listener.wait_for_wake()
    listener.stop()
    """

    def __init__(self, detector: Optional[WakeWordDetector] = None) -> None:
        self._detector = detector or _build_default_detector()
        self._wake_q: queue.Queue[WakeWordResult] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start background detection thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="wake-word")
        self._thread.start()
        logger.debug("WakeWordListener started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def wait_for_wake(self, timeout: Optional[float] = None) -> Optional[WakeWordResult]:
        """Block until a wake word fires or timeout elapses."""
        try:
            return self._wake_q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> None:
        """Discard any pending wake events (e.g. after handling one)."""
        while not self._wake_q.empty():
            try:
                self._wake_q.get_nowait()
            except queue.Empty:
                break
        self._detector.reset()

    # ── internal ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        from openjarvis.voice.listener import SAMPLE_RATE

        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not installed — wake word detection disabled")
            return

        CHUNK = 512
        audio_q: queue.Queue[np.ndarray] = queue.Queue()

        def _cb(indata: np.ndarray, frames: int, ti, status) -> None:  # noqa: ANN001
            audio_q.put(indata.copy())

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK,
            callback=_cb,
        ):
            while not self._stop_event.is_set():
                try:
                    raw = audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                chunk = AudioChunk(
                    data=raw.astype(np.int16).tobytes(),
                    sample_rate=SAMPLE_RATE,
                )
                result = self._detector.process_chunk(chunk)
                if result:
                    self._wake_q.put(result)


def _build_default_detector() -> WakeWordDetector:
    if _OWW_AVAILABLE:
        try:
            return OpenWakeWordDetector()
        except Exception as exc:
            logger.warning("openwakeword init failed (%s) — using energy fallback", exc)
    logger.info("Using energy-spike wake detector (openwakeword not available)")
    return EnergyWakeWordDetector()


__all__ = [
    "EnergyWakeWordDetector",
    "OpenWakeWordDetector",
    "WakeWordListener",
]
