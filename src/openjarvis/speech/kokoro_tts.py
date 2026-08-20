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
import threading
from collections import OrderedDict
from typing import Any, Dict, List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

# Kokoro's voice-prefix → ``lang_code`` mapping. Keep this in sync with
# ``kokoro.pipeline.LANG_CODES``: Kokoro 0.9.x does not expose a Korean
# pipeline, even though Korean voice files have appeared in some catalogs.
_VOICE_PREFIX_TO_LANG: Dict[str, str] = {
    "a": "a",  # American English
    "b": "b",  # British English
    "z": "z",  # Mandarin Chinese
    "j": "j",  # Japanese
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

    def __init__(
        self,
        *,
        model_path: str = "",
        device: str = "auto",
        max_cached_pipelines: int = 4,
    ) -> None:
        if max_cached_pipelines < 1:
            raise ValueError("max_cached_pipelines must be at least 1")
        self._model_path = model_path
        self._device = device
        self._max_cached_pipelines = max_cached_pipelines
        self._model: Any | None = None
        self._pipelines: OrderedDict[str, Any] = OrderedDict()
        # Pipeline creation and inference are both guarded: KPipeline is not
        # documented as thread-safe, and an LRU entry must not be evicted and
        # closed while another thread is still synthesizing with it.
        self._pipeline_lock = threading.RLock()

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
        """Lazily create and retain a bounded LRU of language pipelines."""
        with self._pipeline_lock:
            pipeline = self._pipelines.get(lang_code)
            if pipeline is not None:
                self._pipelines.move_to_end(lang_code)
                return pipeline
            try:
                from kokoro import KPipeline
            except ImportError as exc:
                raise RuntimeError(
                    "kokoro package not installed. Install with: pip install kokoro"
                ) from exc
            try:
                # KModel is language-blind and is by far the heaviest part of
                # Kokoro. Reuse one model across every language pipeline.
                pipeline = KPipeline(lang_code=lang_code, model=self._ensure_model())
            except ImportError as exc:
                # Kokoro loads language-specific G2P resources at init time and
                # several languages need extra dependencies that aren't pulled in
                # by the base ``kokoro`` package. The known cases:
                #   z (Mandarin) → misaki.zh (jieba / pypinyin / ordered-set)
                #   j (Japanese) → misaki.ja (fugashi / unidic-lite)
                # Translate the cryptic ``ordered_set``/``fugashi`` ImportError
                # into a one-line install hint so the user isn't left guessing.
                hints = {
                    "z": 'pip install "misaki[zh]"',
                    "j": 'pip install "misaki[ja]"',
                }
                hint = hints.get(
                    lang_code,
                    f'extra phoneme deps for lang_code="{lang_code}" (see Kokoro docs)',
                )
                raise RuntimeError(
                    f"Kokoro lang_code={lang_code!r} requires extra dependencies. "
                    f"Try: {hint}. Original error: {exc}"
                ) from exc

            self._pipelines[lang_code] = pipeline
            if len(self._pipelines) > self._max_cached_pipelines:
                _, evicted = self._pipelines.popitem(last=False)
                self._cleanup_pipeline(evicted)
            return pipeline

    def _ensure_model(self) -> Any:
        """Load the configured Kokoro model once and move it to the device."""
        if self._model is not None:
            return self._model

        try:
            from kokoro import KModel
        except ImportError as exc:
            raise RuntimeError(
                "kokoro package not installed. Install with: pip install kokoro"
            ) from exc

        device = self._device
        if device == "auto":
            # A real Kokoro install always brings torch. Keeping this fallback
            # makes dependency probes and lightweight mocked tests graceful.
            try:
                import torch
            except ImportError:
                device = "cpu"
            else:
                if torch.cuda.is_available():
                    device = "cuda"
                elif getattr(torch.backends, "mps", None) is not None and (
                    torch.backends.mps.is_available()
                ):
                    device = "mps"
                else:
                    device = "cpu"

        model_kwargs = {"model": self._model_path} if self._model_path else {}
        try:
            self._model = KModel(**model_kwargs).to(device).eval()
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to initialize Kokoro on device {device!r}: {exc}"
            ) from exc
        return self._model

    @staticmethod
    def _cleanup_pipeline(pipeline: Any) -> None:
        """Release resources exposed by a pipeline implementation, if any."""
        close = getattr(pipeline, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # pragma: no cover - third-party cleanup is best effort
                pass

    def close(self) -> None:
        """Release every cached pipeline and clear the cache."""
        with self._pipeline_lock:
            pipelines = list(self._pipelines.values())
            self._pipelines.clear()
            for pipeline in pipelines:
                self._cleanup_pipeline(pipeline)
            self._model = None

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = _DEFAULT_VOICE_ID,
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        import numpy as np
        import soundfile as sf

        lang_code = self._lang_for_voice(voice_id)
        with self._pipeline_lock:
            pipeline = self._ensure_pipeline(lang_code)
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
            "af_heart",
            "af_bella",
            "af_nicole",
            "af_sarah",
            "af_sky",
            "am_adam",
            "am_michael",
            # British English
            "bf_emma",
            "bf_isabella",
            "bm_george",
            "bm_lewis",
            # Mandarin Chinese
            "zf_xiaobei",
            "zf_xiaoni",
            "zf_xiaoxiao",
            "zf_xiaoyi",
            "zm_yunjian",
            "zm_yunxi",
            "zm_yunxia",
            "zm_yunyang",
            # Japanese
            "jf_alpha",
            "jf_gongitsune",
            "jm_kumo",
        ]

    def health(self) -> bool:
        try:
            self._ensure_pipeline(_DEFAULT_LANG_CODE)
            return True
        except RuntimeError:
            return False
