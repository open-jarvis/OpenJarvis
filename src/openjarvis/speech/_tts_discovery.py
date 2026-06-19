"""Auto-discover available text-to-speech backends."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig
    from openjarvis.speech.tts import TTSBackend

DISCOVERY_ORDER = [
    "edge_tts",
    "kokoro",
    "cartesia",
    "openai_tts",
]


def _create_backend(
    key: str,
    config: "JarvisConfig",
) -> Optional["TTSBackend"]:
    from openjarvis.core.registry import TTSRegistry

    if not TTSRegistry.contains(key):
        return None

    try:
        backend_cls = TTSRegistry.get(key)
        if key == "openai_tts":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        return backend_cls()
    except Exception:
        return None


def get_tts_backend(config: "JarvisConfig") -> Optional["TTSBackend"]:
    """Resolve the TTS backend from config."""
    import openjarvis.speech  # noqa: F401

    backend_key = config.speech.tts_backend

    if backend_key != "auto":
        backend = _create_backend(backend_key, config)
        if backend is not None and backend.health():
            return backend
        return None

    for key in DISCOVERY_ORDER:
        backend = _create_backend(key, config)
        if backend is not None and backend.health():
            return backend

    return None
