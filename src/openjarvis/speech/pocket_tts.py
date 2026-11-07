"""Kyutai Pocket TTS backend — streaming TTS, real-time on a CPU or small GPU.

Requires the pocket-tts package: pip install pocket-tts
Falls back gracefully if not installed.
"""

from __future__ import annotations

import io
import threading
from typing import Any, Iterator, List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

# Pocket TTS loads one model per language; voice ids imply their language.
_VOICE_LANGUAGES = {
    "alba": "english",
    "marius": "english",
    "estelle": "french_24l",
}

# Frames are ~12.5 Hz; the library default (max_tokens=50, ~4 s) truncates
# anything longer than a short sentence.
_MAX_TOKENS = 2500


@TTSRegistry.register("pocket")
class PocketTTSBackend(TTSBackend):
    """Kyutai Pocket TTS — local streaming voice synthesis."""

    backend_id = "pocket"

    def __init__(self, *, language: str = "", device: str = "auto") -> None:
        self._language_override = language
        self._device = device
        self._models: dict = {}
        self._voice_states: dict = {}
        # Model loading and inference are guarded: a background preload and
        # the first synthesis can race, and each load costs ~1.5 GB of VRAM.
        self._lock = threading.Lock()

    def _resolve_device(self) -> str:
        if self._device != "auto":
            return self._device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def _ensure_model(self, language: str):
        if language not in self._models:
            try:
                from pocket_tts import TTSModel
            except ImportError:
                raise RuntimeError(
                    "pocket-tts package not installed. "
                    "Install with: pip install pocket-tts"
                )
            device = self._resolve_device()
            # pocket-tts has no device argument: load on CPU, then move.
            # int8 quantization only works on CPU, where it cuts the 24-layer
            # variants' RTF from ~2 to ~1 at some cost in articulation; on a
            # GPU the fp32 model is both faster (RTF ~0.55 on an RTX 3050
            # laptop) and cleaner.
            model = TTSModel.load_model(language=language, quantize=device == "cpu")
            if device != "cpu":
                model = model.to(device)
            self._models[language] = model
        return self._models[language]

    def _ensure_voice_state(self, model, language: str, voice_id: str):
        key = (language, voice_id)
        if key not in self._voice_states:
            self._voice_states[key] = model.get_state_for_audio_prompt(voice_id)
        return self._voice_states[key]

    def _language_for(self, voice_id: str) -> str:
        return self._language_override or _VOICE_LANGUAGES.get(voice_id, "english")

    def preload(self, voice_id: str = "alba") -> None:
        """Load the model and voice, and run one tiny generation.

        The first generation on a fresh model pays one-off kernel and
        allocator setup; doing it here keeps it out of the first reply.
        """
        language = self._language_for(voice_id)
        with self._lock:
            model = self._ensure_model(language)
            state = self._ensure_voice_state(model, language, voice_id)
            model.generate_audio(state, "Bonjour.", max_tokens=_MAX_TOKENS)

    def synthesize_stream(
        self,
        text: str,
        *,
        voice_id: str = "alba",
        speed: float = 1.0,  # pocket-tts has no speed control; interface parity
    ) -> Iterator[tuple[Any, int]]:
        """Yield ``(float32 mono samples, sample_rate)`` frames as they decode.

        The first frame arrives ~120 ms after the call on an RTX 3050
        laptop, against several seconds for :meth:`synthesize` on a long
        sentence, which has to finish the whole sentence first.
        """
        language = self._language_for(voice_id)
        with self._lock:
            model = self._ensure_model(language)
            state = self._ensure_voice_state(model, language, voice_id)
            rate = int(model.sample_rate)
            for frame in model.generate_audio_stream(
                state, text, max_tokens=_MAX_TOKENS
            ):
                samples = frame.detach().cpu().numpy().reshape(-1)
                if samples.size:
                    yield samples.astype("float32", copy=False), rate

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "alba",
        speed: float = 1.0,  # pocket-tts has no speed control; interface parity
        output_format: str = "wav",
    ) -> TTSResult:
        language = self._language_for(voice_id)
        with self._lock:
            model = self._ensure_model(language)
            state = self._ensure_voice_state(model, language, voice_id)
            audio = model.generate_audio(state, text, max_tokens=_MAX_TOKENS)

        import soundfile as sf

        samples = audio.detach().cpu().numpy()
        if samples.ndim > 1:
            samples = samples.squeeze()
        if samples.size == 0:
            return TTSResult(audio=b"", format=output_format, voice_id=voice_id)

        sample_rate = int(model.sample_rate)
        buf = io.BytesIO()
        sf.write(buf, samples, sample_rate, format=output_format.upper())
        buf.seek(0)

        return TTSResult(
            audio=buf.read(),
            format=output_format,
            voice_id=voice_id,
            sample_rate=sample_rate,
            duration_seconds=len(samples) / sample_rate,
            metadata={"backend": "pocket", "language": language},
        )

    def available_voices(self) -> List[str]:
        return list(_VOICE_LANGUAGES)

    def health(self) -> bool:
        try:
            import pocket_tts  # noqa: F401

            return True
        except ImportError:
            return False
