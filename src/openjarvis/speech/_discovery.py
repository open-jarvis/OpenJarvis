"""Auto-discover available speech-to-text backends."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig
    from openjarvis.speech._stubs import SpeechBackend

# Priority order: local first, then cloud
DISCOVERY_ORDER = [
    "faster-whisper",
    "openai",
    "deepgram",
]

# Safe automatic selection never crosses a network/provider boundary. Cloud
# providers remain available only when explicitly named in configuration.
LOCAL_DISCOVERY_ORDER = ["faster-whisper"]


def _create_backend(
    key: str,
    config: "JarvisConfig",
) -> Optional["SpeechBackend"]:
    """Try to instantiate a speech backend by registry key."""
    from openjarvis.core.registry import SpeechRegistry

    if not SpeechRegistry.contains(key):
        return None

    try:
        backend_cls = SpeechRegistry.get(key)

        if key == "faster-whisper":
            return backend_cls(
                model_size=config.speech.model,
                device=config.speech.device,
                compute_type=config.speech.compute_type,
                download_root=config.speech.stt_runtime_path or None,
            )
        elif key == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        elif key == "deepgram":
            api_key = os.environ.get("DEEPGRAM_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        else:
            return backend_cls()
    except Exception:
        return None


def get_speech_backend(config: "JarvisConfig") -> Optional["SpeechBackend"]:
    """Resolve the speech backend from config.

    If ``config.speech.backend`` is ``"auto"``, tries backends in
    priority order and returns the first healthy one.
    """
    # Importing the package registers built-ins during normal startup. Re-add
    # an already imported backend if a test or an embedded host cleared the
    # process-wide registry afterwards.
    import openjarvis.speech  # noqa: F401
    from openjarvis.core.registry import SpeechRegistry

    builtin_backends: dict[str, tuple[str, str]] = {
        "faster-whisper": (
            "openjarvis.speech.faster_whisper",
            "FasterWhisperBackend",
        ),
        "openai": ("openjarvis.speech.openai_whisper", "OpenAIWhisperBackend"),
        "deepgram": ("openjarvis.speech.deepgram", "DeepgramSpeechBackend"),
    }
    for key, (module_name, class_name) in builtin_backends.items():
        if SpeechRegistry.contains(key):
            continue
        try:
            module = __import__(module_name, fromlist=[class_name])
            SpeechRegistry.register_value(key, getattr(module, class_name))
        except (ImportError, AttributeError):
            continue

    backend_key = config.speech.backend

    if backend_key != "auto":
        return _create_backend(backend_key, config)

    # Auto-discovery is local-only. Merely finding an API key in the process
    # environment must never activate an external speech service.
    for key in LOCAL_DISCOVERY_ORDER:
        backend = _create_backend(key, config)
        if backend is not None:
            return backend

    return None
