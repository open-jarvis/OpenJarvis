"""Kokoro TTS backend — fully open-source, runs locally.

Requires the kokoro package: pip install kokoro
Falls back gracefully if not installed.

Kokoro v1.x supports multiple languages. Each language has its own
``KPipeline`` (the model loads language-specific G2P resources at init).
This backend lazily creates one pipeline per language code, derived from
the voice ID prefix per Kokoro's naming convention
``{lang_prefix}{gender}_{name}`` — e.g. ``zf_xiaoxiao`` is Mandarin
female (prefix ``z`` → ``lang_code="z"``).
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult


# Kokoro's voice-prefix → ``lang_code`` mapping. Each lang_code spins up
# a separate KPipeline; pipelines are cached for the backend's lifetime.
_VOICE_PREFIX_TO_LANG: Dict[str, str] = {
    "a": "a",  # American English
    "b": "b",  # British English
    "z": "z",  # Mandarin Chinese
    "j": "j",  # Japanese
    "k": "k",  # Korean
    "f": "f",  # French
    "i": "i",  # Italian
    "p": "p",  # Brazilian Portuguese
    "h": "h",  # Hindi
    "e": "e",  # Spanish
}

_DEFAULT_LANG_CODE = "a"
_DEFAULT_VOICE_ID = "af_heart"


@TTSRegistry.register("kokoro")
class KokoroTTSBackend(TTSBackend):
    """Kokoro TTS — local open-source voice synthesis, multilingual."""

    backend_id = "kokoro"

    def __init__(self, *, model_path: str = "", device: str = "auto") -> None:
        self._model_path = model_path
        self._device = device
        self._pipelines: Dict[str, Any] = {}

    @staticmethod
    def _lang_for_voice(voice_id: str) -> str:
        """Return the Kokoro ``lang_code`` for a voice ID.

        Voice IDs follow the convention ``{lang}{gender}_{name}`` where
        ``lang`` is a single letter prefix (e.g. ``z`` for Mandarin in
        ``zf_xiaoxiao``). Falls back to American English if the prefix is
        unknown.
        """
        if not voice_id:
            return _DEFAULT_LANG_CODE
        return _VOICE_PREFIX_TO_LANG.get(voice_id[:1], _DEFAULT_LANG_CODE)

    def _ensure_pipeline(self, lang_code: str) -> Any:
        """Lazily create and cache a ``KPipeline`` per language code."""
        if lang_code in self._pipelines:
            return self._pipelines[lang_code]
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise RuntimeError(
                "kokoro package not installed. Install with: pip install kokoro"
            ) from exc
        pipeline = KPipeline(lang_code=lang_code)
        self._pipelines[lang_code] = pipeline
        return pipeline

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = _DEFAULT_VOICE_ID,
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        lang_code = self._lang_for_voice(voice_id)
        pipeline = self._ensure_pipeline(lang_code)

        import numpy as np
        import soundfile as sf

        samples = []
        for _, _, audio in pipeline(text, voice=voice_id, speed=speed):
            samples.append(audio)

        if not samples:
            return TTSResult(
                audio=b"",
                format=output_format,
                voice_id=voice_id,
                metadata={"backend": "kokoro", "lang_code": lang_code},
            )

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
            metadata={"backend": "kokoro", "lang_code": lang_code},
        )

    def available_voices(self) -> List[str]:
        # Curated subset of Kokoro v1.x voices. The full catalog is larger;
        # the list here covers the languages OpenJarvis users most commonly
        # ask for and avoids voice IDs that have changed across Kokoro
        # releases.
        return [
            # American English
            "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
            "am_adam", "am_michael",
            # British English
            "bf_emma", "bf_isabella", "bm_george", "bm_lewis",
            # Mandarin Chinese
            "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
            "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
            # Japanese
            "jf_alpha", "jf_gongitsune", "jm_kumo",
        ]

    def health(self) -> bool:
        try:
            self._ensure_pipeline(_DEFAULT_LANG_CODE)
            return True
        except RuntimeError:
            return False
