"""Wake-word detection backend using openWakeWord.

Ported from an early standalone prototype (modules/wakeword.py) into the
real speech-backend architecture: a proper ``WakeWordRegistry`` entry
alongside the existing STT/TTS backends, config-driven instead of
hardcoded constants, and with a ``stop()`` escape hatch so a caller can
break a blocked ``listen()`` from another thread.
"""

from __future__ import annotations

import threading
from typing import Optional

from openjarvis.core.registry import WakeWordRegistry
from openjarvis.speech._stubs import WakeWordBackend

# openWakeWord's bundled models are trained on 16 kHz mono audio. Many
# microphones default to a higher native rate, so we capture at
# _CAPTURE_SAMPLE_RATE and naively decimate down to _MODEL_SAMPLE_RATE --
# adequate for wake-word detection (short trigger phrase, not
# transcription-quality audio).
_MODEL_SAMPLE_RATE = 16000
_CAPTURE_SAMPLE_RATE = 48000
_CHUNK_SECONDS = 0.08


@WakeWordRegistry.register("openwakeword")
class OpenWakeWordBackend(WakeWordBackend):
    """Always-on wake-word detector using the openWakeWord library."""

    backend_id = "openwakeword"

    def __init__(
        self,
        *,
        model: str = "hey_jarvis",
        threshold: float = 0.5,
        mic_device: Optional[int] = None,
    ) -> None:
        self._model_name = model
        self._threshold = threshold
        self._mic_device = mic_device
        self._model = None
        self._stop_event = threading.Event()

    def _ensure_model(self):
        if self._model is None:
            from openwakeword.model import Model

            self._model = Model(
                inference_framework="onnx",
                wakeword_models=[self._model_name],
            )
        return self._model

    def health(self) -> bool:
        try:
            self._ensure_model()
            import sounddevice as sd

            sd.check_input_settings(
                device=self._mic_device,
                samplerate=_CAPTURE_SAMPLE_RATE,
                channels=1,
            )
            return True
        except Exception:
            return False

    def stop(self) -> None:
        self._stop_event.set()

    def listen(self) -> bool:
        """Block until the wake word is detected, or ``stop()`` is called."""
        import sounddevice as sd

        model = self._ensure_model()
        chunk_size = int(_CAPTURE_SAMPLE_RATE * _CHUNK_SECONDS)
        downsample_factor = _CAPTURE_SAMPLE_RATE // _MODEL_SAMPLE_RATE

        self._stop_event.clear()
        model.reset()

        with sd.InputStream(
            device=self._mic_device,
            samplerate=_CAPTURE_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=chunk_size,
            latency="high",
        ) as stream:
            while not self._stop_event.is_set():
                audio, _ = stream.read(chunk_size)
                audio = audio.flatten()[::downsample_factor]
                prediction = model.predict(audio)
                score = prediction.get(self._model_name, 0.0)
                if score > self._threshold:
                    model.reset()
                    return True

        return False


__all__ = ["OpenWakeWordBackend"]
