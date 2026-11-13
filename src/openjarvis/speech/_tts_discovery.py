"""Auto-discover available text-to-speech backends.

Mirrors ``speech/_discovery.py``, which does the same for speech-to-text. The
selection rules used to live in ``cli/_voice_chat.py``; they moved here so the
API server can reuse them instead of importing from the CLI package.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig

logger = logging.getLogger(__name__)

# Priority order: local first, then cloud.
TTS_BACKEND_ORDER = ("kokoro", "openai_tts", "cartesia", "elevenlabs")

# Voice IDs are backend-specific and NOT portable. ``speech.voice_id`` applies
# only to ``speech.tts_backend``; if synthesis falls back to another backend we
# use that backend's own default rather than passing an unrecognized ID through.
BACKEND_DEFAULT_VOICE = {
    "kokoro": "bm_george",  # British male
    "openai_tts": "onyx",  # deepest OpenAI preset
    "cartesia": "",  # no safe static default; let Cartesia choose
    "elevenlabs": "JBFqnCBsd6RMkjVDRZzb",  # "George", British male
}


def default_voice_for(backend_id: str) -> str:
    """Return the fallback voice ID for *backend_id*, or an empty string."""
    return BACKEND_DEFAULT_VOICE.get(backend_id, "")


def get_tts_backend(
    preferred: str = "",
    *,
    attempted: Optional[set[str]] = None,
    device: str = "auto",
) -> Optional[Any]:
    """Return the first healthy TTS backend, preferring *preferred*.

    ``attempted`` lets a caller carry state across calls so a backend that
    already failed is not retried; it is mutated in place.

    ``device`` is the compute device for local synthesis, mirroring how
    ``_discovery._create_backend`` forwards ``speech.device`` to
    faster-whisper. Without it Kokoro defaults to ``"auto"`` and claims the
    GPU, which fails with CUDA OOM when a local LLM already holds the VRAM.
    See :func:`_create_backend` for which backends take it.
    """
    # Import triggers built-in backend registration only when voice output is
    # actually requested.
    import openjarvis.speech  # noqa: F401
    from openjarvis.core.registry import TTSRegistry

    seen = attempted if attempted is not None else set()

    for key in dict.fromkeys((preferred, *TTS_BACKEND_ORDER)):
        if not key or key in seen:
            continue
        seen.add(key)
        if not TTSRegistry.contains(key):
            continue
        try:
            candidate = _create_backend(key, device)
            if candidate is not None and candidate.health():
                return candidate
        except Exception:
            logger.debug("TTS backend %s unavailable", key, exc_info=True)
            continue
    return None


def _create_backend(key: str, device: str) -> Optional[Any]:
    """Instantiate the TTS backend registered under *key*.

    Mirrors ``_discovery._create_backend``: which constructor arguments a
    backend takes is stated explicitly per key rather than inferred, so adding
    a backend that needs configuration is a visible edit here. Only local
    backends take a compute device; the cloud ones synthesize server-side.
    """
    from openjarvis.core.registry import TTSRegistry

    backend_cls = TTSRegistry.get(key)

    if key == "kokoro":
        return backend_cls(device=device)
    return backend_cls()


def tts_device_for(config: "JarvisConfig") -> str:
    """Resolve the TTS compute device, falling back to ``speech.device``."""
    speech = getattr(config, "speech", None)
    tts_device = (getattr(speech, "tts_device", "") or "").strip()
    if tts_device:
        return tts_device
    return (getattr(speech, "device", "") or "auto").strip() or "auto"


def voice_preferences(config: "JarvisConfig") -> tuple[str, str, float]:
    """Resolve ``(tts_backend, voice_id, speed)`` from *config*."""
    speech = getattr(config, "speech", None)
    return (
        getattr(speech, "tts_backend", "kokoro") or "kokoro",
        getattr(speech, "voice_id", "") or "",
        float(getattr(speech, "voice_speed", 1.0)),
    )


__all__ = [
    "BACKEND_DEFAULT_VOICE",
    "TTS_BACKEND_ORDER",
    "default_voice_for",
    "get_tts_backend",
    "tts_device_for",
    "voice_preferences",
]
