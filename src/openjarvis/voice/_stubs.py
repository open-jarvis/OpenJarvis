"""Abstract base classes for the voice subsystem."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Iterator, Optional


class VoiceState(Enum):
    IDLE = auto()
    WAKE_DETECTED = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()


@dataclass
class AudioChunk:
    """Raw audio data from the microphone."""
    data: bytes          # raw PCM bytes
    sample_rate: int     # e.g. 16000
    channels: int = 1
    sample_width: int = 2  # bytes per sample (int16 = 2)


@dataclass
class WakeWordResult:
    word: str
    confidence: float = 1.0


class WakeWordDetector(ABC):
    """Detects a wake word in a stream of audio chunks."""

    @abstractmethod
    def process_chunk(self, chunk: AudioChunk) -> Optional[WakeWordResult]:
        """Return a result if the wake word was detected, else None."""

    @abstractmethod
    def reset(self) -> None:
        """Reset internal state after a wake event."""


class TTSBackend(ABC):
    """Text-to-speech backend."""

    @abstractmethod
    def speak(self, text: str, *, on_word: Optional[Callable[[str], None]] = None) -> None:
        """Synthesize and play text. Blocks until complete or interrupted."""

    @abstractmethod
    def stop(self) -> None:
        """Interrupt any ongoing playback immediately."""

    @abstractmethod
    def is_speaking(self) -> bool:
        """Return True if audio is currently playing."""


__all__ = ["AudioChunk", "TTSBackend", "VoiceState", "WakeWordDetector", "WakeWordResult"]
