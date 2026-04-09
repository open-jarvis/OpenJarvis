"""Auto-discover available text-to-speech backends.

Mirrors the pattern of ``openjarvis.speech._discovery`` for STT.

Priority order (local-first):
    1. kokoro    — fully local, open-source, no API key
    2. openai_tts — cloud, needs OPENAI_API_KEY
    3. cartesia  — cloud, needs CARTESIA_API_KEY
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig
    from openjarvis.speech.tts import TTSBackend

# Ordered by preference: local first, then cloud
_DISCOVERY_ORDER = ["kokoro", "openai_tts", "cartesia"]


def _create_tts(key: str, config: "JarvisConfig") -> Optional["TTSBackend"]:
    """Try to instantiate a TTS backend by registry key."""
    # Trigger registration of all TTS backends
    import openjarvis.speech  # noqa: F401

    from openjarvis.core.registry import TTSRegistry

    if not TTSRegistry.contains(key):
        return None

    try:
        backend_cls = TTSRegistry.get(key)

        if key == "kokoro":
            backend = backend_cls(device=config.speech.device)
        elif key == "openai_tts":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return None
            backend = backend_cls(api_key=api_key)
        elif key == "cartesia":
            api_key = os.environ.get("CARTESIA_API_KEY", "")
            if not api_key:
                return None
            backend = backend_cls(api_key=api_key)
        else:
            backend = backend_cls()

        if backend.health():
            return backend
        return None
    except Exception:
        return None


def get_tts_backend(config: "JarvisConfig") -> Optional["TTSBackend"]:
    """Resolve the TTS backend from config.

    If ``config.speech.tts_backend`` is ``"auto"``, tries backends in
    priority order and returns the first healthy one.

    Returns ``None`` if no backend is available (TTS will be skipped).
    """
    key = config.speech.tts_backend

    if key != "auto":
        return _create_tts(key, config)

    for candidate in _DISCOVERY_ORDER:
        backend = _create_tts(candidate, config)
        if backend is not None:
            return backend

    return None
