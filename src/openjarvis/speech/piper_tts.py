"""Piper TTS backend — local neural voice synthesis, multilingual.

Piper covers languages Kokoro does not, German among them, and it phonemizes
with an espeak-ng copy bundled inside the wheel, so unlike Kokoro it needs no
system-level espeak-ng install.

Requires the piper-tts package: pip install "openjarvis[voice-piper]"

Voice IDs follow Piper's own naming convention, ``{lang}_{REGION}-{name}-{quality}``
— e.g. ``de_DE-thorsten-medium``. A voice that is not on disk yet is downloaded
on first use into ``$OPENJARVIS_HOME/piper_voices`` (override with
``PIPER_VOICE_DIR``).
"""

from __future__ import annotations

import io
import logging
import os
import threading
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Any, List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

logger = logging.getLogger(__name__)

_DEFAULT_VOICE_ID = "en_US-lessac-medium"

# Piper loads one ONNX session per voice; keep a small LRU so switching voices
# does not leak sessions the way an unbounded dict would.
_MAX_CACHED_VOICES = 3


def _voice_dir() -> Path:
    """Directory that holds downloaded ``.onnx`` / ``.onnx.json`` voice pairs."""
    override = os.environ.get("PIPER_VOICE_DIR")
    if override:
        return Path(override).expanduser()

    from openjarvis.core.paths import get_config_dir

    return get_config_dir() / "piper_voices"


@TTSRegistry.register("piper")
class PiperTTSBackend(TTSBackend):
    """Piper TTS — local open-source voice synthesis, multilingual."""

    backend_id = "piper"

    def __init__(self, *, voice_dir: str | Path | None = None) -> None:
        self._voice_dir = Path(voice_dir) if voice_dir else None
        self._voices: OrderedDict[str, Any] = OrderedDict()
        self._catalog: List[str] | None = None
        self._lock = threading.Lock()

    # -- voice loading ----------------------------------------------------

    def _resolve_voice_dir(self) -> Path:
        return self._voice_dir if self._voice_dir is not None else _voice_dir()

    def _ensure_voice(self, voice_id: str) -> Any:
        """Lazily load a voice, downloading it on first use, keeping an LRU."""
        with self._lock:
            voice = self._voices.get(voice_id)
            if voice is not None:
                self._voices.move_to_end(voice_id)
                return voice

            try:
                from piper import PiperVoice
            except ImportError as exc:
                raise RuntimeError(
                    "piper package not installed. "
                    'Install with: pip install "openjarvis[voice-piper]"'
                ) from exc

            directory = self._resolve_voice_dir()
            directory.mkdir(parents=True, exist_ok=True)
            model_path = directory / f"{voice_id}.onnx"

            if not model_path.exists():
                from piper.download_voices import download_voice

                logger.info("Downloading Piper voice %s to %s", voice_id, directory)
                download_voice(voice_id, directory)

            voice = PiperVoice.load(model_path)

            self._voices[voice_id] = voice
            while len(self._voices) > _MAX_CACHED_VOICES:
                self._voices.popitem(last=False)
            return voice

    # -- TTSBackend -------------------------------------------------------

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        if output_format != "wav":
            raise ValueError(
                f"Piper synthesizes WAV only, got output_format={output_format!r}"
            )

        from piper import SynthesisConfig

        resolved_id = voice_id or _DEFAULT_VOICE_ID
        voice = self._ensure_voice(resolved_id)

        # Piper scales duration, not rate: a longer utterance is a slower one,
        # so the caller's speed multiplier is its reciprocal.
        length_scale = 1.0 / speed if speed > 0 else 1.0

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            voice.synthesize_wav(
                text, wav_file, SynthesisConfig(length_scale=length_scale)
            )
        audio = buf.getvalue()

        sample_rate = getattr(voice.config, "sample_rate", 22050)
        with wave.open(io.BytesIO(audio), "rb") as probe:
            duration = probe.getnframes() / float(probe.getframerate() or sample_rate)

        return TTSResult(
            audio=audio,
            format="wav",
            duration_seconds=duration,
            voice_id=resolved_id,
            sample_rate=sample_rate,
            metadata={"backend": "piper"},
        )

    def _local_voices(self) -> List[str]:
        directory = self._resolve_voice_dir()
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.onnx"))

    def available_voices(self) -> List[str]:
        """Every voice Piper publishes, falling back to the ones already on disk.

        ``piper.download_voices.list_voices`` prints to stdout and returns None,
        so the catalog is read straight from the JSON index instead. The result
        is cached per instance; a failed fetch degrades to the local voices
        rather than raising.
        """
        if self._catalog is not None:
            return self._catalog

        try:
            import httpx
            from piper.download_voices import VOICES_JSON

            resp = httpx.get(VOICES_JSON, timeout=10.0, follow_redirects=True)
            resp.raise_for_status()
            self._catalog = sorted(resp.json().keys())
        except Exception:
            logger.debug("Piper voice catalog unreachable", exc_info=True)
            return self._local_voices()

        return self._catalog

    def health(self) -> bool:
        try:
            import piper  # noqa: F401
        except ImportError:
            return False
        return True
