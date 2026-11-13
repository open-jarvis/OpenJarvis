"""Audio-level wake word detection (openWakeWord).

The transcript-based check in ``speech/wake_word.py`` only runs *after* a
recording has been transcribed. This module adds the always-listening layer
inspired by openWakeWord: the microphone is streamed continuously and an ONNX
model scores short audio frames; when the wake phrase (e.g. "hey jarvis")
crosses a confidence threshold, Jarvis starts listening for a command.

``openwakeword`` (and ``sounddevice``) are optional: when either is missing,
:meth:`AudioWakeWordDetector.build` returns ``None`` and callers fall back to
the transcript-based check, so voice chat keeps working without the extra
dependency.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_CHUNK_MS = 80  # openWakeWord is trained on 80 ms frames
_CHUNK_SAMPLES = int(_SAMPLE_RATE * _CHUNK_MS / 1000)

# Pretrained openWakeWord models that ship with the ``openwakeword`` package.
DEFAULT_WAKE_MODELS = ("hey_jarvis_v0.1",)

# After a detection, ignore further triggers for this long so the chime of
# the follow-up recording is not immediately re-detected.
_REFRACTORY_SECONDS = 1.0


def unavailable_reason() -> Optional[str]:
    """Return why audio wake-word detection is unavailable, or ``None``.

    Uses ``importlib.util.find_spec`` — deliberately NOT an import, because
    importing ``openwakeword`` pulls in onnxruntime (seconds to tens of
    seconds) and may touch the network. ``None`` means both packages are
    installed; the slow import itself happens lazily inside the detector.
    """
    import importlib.util

    if importlib.util.find_spec("openwakeword") is None:
        return (
            "openwakeword is not installed — install with: "
            "pip install openwakeword"
        )
    if importlib.util.find_spec("sounddevice") is None:
        return (
            "sounddevice is not installed — install with: "
            "pip install sounddevice"
        )
    return None


def _max_score(prediction: Any) -> float:
    """Return the highest model score in an openWakeWord prediction dict."""
    if not isinstance(prediction, dict):
        return 0.0
    values = [v for v in prediction.values() if isinstance(v, (int, float))]
    return max(values) if values else 0.0


class AudioWakeWordDetector:
    """Streams the microphone through an openWakeWord model until a trigger.

    ``model_factory`` and ``stream_factory`` are injection seams for tests:
    they receive no arguments and must return, respectively, an object with a
    ``predict(frame) -> dict`` method and a context manager yielding an object
    with ``read(n) -> bytes``.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        wake_models: Sequence[str] = DEFAULT_WAKE_MODELS,
        timeout: float = 30.0,
        sample_rate: int = _SAMPLE_RATE,
        chunk_samples: int = _CHUNK_SAMPLES,
        model_factory: Optional[Callable[[], Any]] = None,
        stream_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._threshold = threshold
        self._wake_models = tuple(wake_models)
        self._timeout = timeout
        self._sample_rate = sample_rate
        self._chunk_samples = chunk_samples
        self._model_factory = model_factory or self._default_model
        self._stream_factory = stream_factory or self._default_stream
        self._model: Any = None
        self.load_error: Optional[str] = None

    # -- factories -----------------------------------------------------------

    def _default_model(self) -> Any:
        # Importing openwakeword is slow (onnxruntime) and its first import
        # may probe HuggingFace for model files; force offline so the import
        # never blocks on the network. Pretrained models bundled with the
        # package (e.g. hey_jarvis_v0.1) load without downloading.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from openwakeword import Model

        return Model(
            wakeword_models=list(self._wake_models),
            inference_framework="onnx",
        )

    def _default_stream(self) -> Any:
        import sounddevice as sd

        return sd.RawInputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self._chunk_samples,
        )

    # -- lifecycle -----------------------------------------------------------

    def load(self) -> None:
        """Build the wake-word model (idempotent)."""
        if self._model is None:
            self._model = self._model_factory()

    def listen(self) -> bool:
        """Listen on the microphone until a wake word fires or time runs out.

        Returns ``True`` when the wake phrase was detected, ``False`` on
        timeout or when the model cannot be loaded (missing weights, no mic).
        """
        try:
            self.load()
        except Exception as exc:  # noqa: BLE001 — missing model = no wake word
            self.load_error = str(exc)
            logger.warning("Wake-word model failed to load: %s", exc)
            return False
        self.load_error = None
        max_chunks = max(1, int(self._timeout * 1000 / _CHUNK_MS))
        model = self._model
        try:
            import numpy as np

            with self._stream_factory() as stream:
                for _ in range(max_chunks):
                    raw, _ = stream.read(self._chunk_samples)
                    # openWakeWord expects float32 audio in [-1, 1], not raw
                    # 16-bit PCM bytes.
                    samples = (
                        np.frombuffer(bytes(raw), dtype=np.int16).astype(
                            np.float32
                        )
                        / 32768.0
                    )
                    prediction = model.predict(samples)
                    if _max_score(prediction) >= self._threshold:
                        self._reset_model(model)
                        return True
        except Exception as exc:  # noqa: BLE001 — mic hiccups are not fatal
            logger.warning("Audio wake-word listening failed: %s", exc)
            return False
        self._reset_model(model)
        return False

    @staticmethod
    def _reset_model(model: Any) -> None:
        """Clear a model's internal state between detections (best-effort)."""
        reset = getattr(model, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:  # noqa: BLE001 — state reset is best-effort
                logger.debug("Wake-word model reset failed", exc_info=True)

    def close(self) -> None:
        """Release the model (idempotent)."""
        model, self._model = self._model, None
        close = getattr(model, "close", None) if model is not None else None
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 — cleanup must not raise
                logger.debug("Wake-word model close failed", exc_info=True)


def build_detector(
    *,
    threshold: float = 0.5,
    wake_models: Sequence[str] = DEFAULT_WAKE_MODELS,
    timeout: float = 30.0,
) -> Optional[AudioWakeWordDetector]:
    """Return a ready-to-use detector, or ``None`` when unavailable.

    Never raises — when ``openwakeword``/``sounddevice`` are missing (or a
    pretrained model file is absent) the caller falls back to the
    transcript-based wake-word check.
    """
    reason = unavailable_reason()
    if reason is not None:
        logger.debug("Audio wake word unavailable: %s", reason)
        return None
    return AudioWakeWordDetector(
        threshold=threshold,
        wake_models=wake_models,
        timeout=timeout,
    )


def wait_for_wake_word(
    *,
    threshold: float = 0.5,
    wake_models: Sequence[str] = DEFAULT_WAKE_MODELS,
    timeout: float = 30.0,
) -> Optional[bool]:
    """Convenience wrapper: listen once, releasing the model afterwards.

    Returns ``True``/``False`` (detected / timeout) or ``None`` when audio
    wake-word detection is unavailable on this machine.
    """
    detector = build_detector(
        threshold=threshold,
        wake_models=wake_models,
        timeout=timeout,
    )
    if detector is None:
        return None
    try:
        return detector.listen()
    finally:
        detector.close()


__all__ = [
    "AudioWakeWordDetector",
    "DEFAULT_WAKE_MODELS",
    "build_detector",
    "unavailable_reason",
    "wait_for_wake_word",
]
