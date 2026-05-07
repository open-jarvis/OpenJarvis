"""Kokoro TTS backend — fully open-source, runs locally.

Requires the kokoro package: pip install kokoro
Falls back gracefully if not installed.
"""

from __future__ import annotations

import io
from typing import List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult


@TTSRegistry.register("kokoro")
class KokoroTTSBackend(TTSBackend):
    """Kokoro TTS — local open-source voice synthesis."""

    backend_id = "kokoro"

    def __init__(self, *, model_path: str = "", device: str = "auto") -> None:
        self._model_path = model_path
        self._device = device
        self._pipeline = None

    def _ensure_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        try:
            from kokoro import KPipeline

            self._pipeline = KPipeline(lang_code="a")
        except ImportError:
            raise RuntimeError(
                "kokoro package not installed. Install with: pip install kokoro"
            )

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "af_heart",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        self._ensure_pipeline()
        import numpy as np
        import soundfile as sf

        samples = []
        for _, _, audio in self._pipeline(text, voice=voice_id, speed=speed):
            samples.append(audio)

        if not samples:
            return TTSResult(audio=b"", format=output_format, voice_id=voice_id)

        combined = np.concatenate(samples)
        buf = io.BytesIO()
        sf.write(buf, combined, 24000, format=output_format.upper())
        buf.seek(0)

        return TTSResult(
            audio=buf.read(),
            format=output_format,
            voice_id=voice_id,
            sample_rate=24000,
            duration_seconds=len(combined) / 24000,
            metadata={"backend": "kokoro"},
        )

    def available_voices(self) -> List[str]:
        # Kokoro ships with many more voices than the four originally
        # exposed here. Surface accent/gender variants so users can pick
        # a Jarvis-adjacent (calm British male) or Friday-adjacent
        # (calm British female) voice without paying for a third-party
        # TTS provider. Voice ids follow Kokoro's <accent><gender>_<name>
        # convention: a=American, b=British; f=female, m=male.
        return [
            # American female
            "af_heart",
            "af_bella",
            "af_nicole",
            "af_sarah",
            "af_sky",
            # American male
            "am_adam",
            "am_michael",
            # British female (Friday-adjacent)
            "bf_emma",
            "bf_isabella",
            # British male (Jarvis-adjacent)
            "bm_george",
            "bm_lewis",
        ]

    def health(self) -> bool:
        try:
            self._ensure_pipeline()
            return True
        except RuntimeError:
            return False
