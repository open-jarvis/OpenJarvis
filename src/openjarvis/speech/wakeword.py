"""Local wake-word detection via openWakeWord (MIT, ONNX, fully offline).

Single implementation for v1 — no registry abstraction (promote to a
``SpeechRegistry``-style registry only if/when a second wake-word engine is
actually added; premature to build that now for one engine). Requires the
optional ``speech-wakeword`` extra (``openwakeword``, ``sounddevice``,
``numpy``) — importing this module without it raises ``ImportError``, which
callers (``build_voice_service``) treat as "feature unavailable", never as
a hard crash.
"""

from __future__ import annotations

from typing import Any, Optional


class WakeWordDetector:
    """Wraps an openWakeWord model — feed it audio chunks, get wake-word hits."""

    def __init__(self, wake_word: str = "hey_jarvis", threshold: float = 0.5) -> None:
        self._wake_word = wake_word
        self._threshold = threshold
        self._model: Optional[Any] = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from openwakeword.model import Model  # type: ignore[import-not-found]

            self._model = Model(wakeword_models=[self._wake_word])
        return self._model

    def process_chunk(self, pcm_chunk: Any) -> Optional[str]:
        """Feed one audio chunk (int16 PCM, 16kHz mono). Returns the wake word

        name if detected above threshold this chunk, else ``None``.
        """
        model = self._ensure_model()
        predictions = model.predict(pcm_chunk)
        for name, score in predictions.items():
            if score >= self._threshold:
                return name
        return None

    def reset(self) -> None:
        """Clear internal prediction buffers (call after a detection is consumed)."""
        if self._model is not None and hasattr(self._model, "reset"):
            self._model.reset()


__all__ = ["WakeWordDetector"]
