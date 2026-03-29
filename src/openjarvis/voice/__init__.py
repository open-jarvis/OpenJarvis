"""Voice assistant subsystem for OpenJarvis.

Components
----------
listener    — microphone input + VAD
wake_word   — wake word detection (openwakeword / energy fallback)
tts         — text-to-speech (Piper / macOS say / silent)
speech_filter — cleans LLM responses for spoken delivery
loop        — main always-on voice loop
"""

from openjarvis.voice.loop import VoiceLoop
from openjarvis.voice.tts import build_tts
from openjarvis.voice.speech_filter import prepare_for_speech

__all__ = ["VoiceLoop", "build_tts", "prepare_for_speech"]
