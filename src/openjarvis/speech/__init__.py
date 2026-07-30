"""Speech subsystem — speech-to-text and text-to-speech backends."""

import importlib

from openjarvis.speech.providers import (
    DisabledSpeechToTextProvider,
    DisabledTextToSpeechProvider,
    SpeechProviderCapabilities,
    SpeechToTextProvider,
    TextToSpeechProvider,
)

# Optional STT backends — each registers itself via @SpeechRegistry.register()
for _mod in ("faster_whisper", "openai_whisper", "deepgram"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass

# Optional TTS backends — each registers itself via @TTSRegistry.register()

__all__ = [
    "DisabledSpeechToTextProvider",
    "DisabledTextToSpeechProvider",
    "SpeechProviderCapabilities",
    "SpeechToTextProvider",
    "TextToSpeechProvider",
]
for _mod in ("cartesia_tts", "kokoro_tts", "openai_tts"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass
