"""Local voice input support for Friday app mode."""

from openjarvis.voice.adapters import (
    STTAdapter,
    STTResult,
    create_stt_adapter,
)
from openjarvis.voice.recorder import AudioRecorder, RecordingError
from openjarvis.voice.service import ListenOnceResult, listen_once
from openjarvis.voice.tts import (
    SpeakResult,
    cleanup_tts_text,
    speak_macos_say,
    split_tts_chunks,
    stop_macos_say,
)

__all__ = [
    "AudioRecorder",
    "ListenOnceResult",
    "RecordingError",
    "STTAdapter",
    "STTResult",
    "SpeakResult",
    "create_stt_adapter",
    "cleanup_tts_text",
    "listen_once",
    "speak_macos_say",
    "split_tts_chunks",
    "stop_macos_say",
]
