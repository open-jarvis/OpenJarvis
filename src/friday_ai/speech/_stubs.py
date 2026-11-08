"""Abstract base classes and data types for the speech subsystem."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Segment:
    """A timed segment of transcribed text."""

    text: str
    start: float  # Start time in seconds
    end: float  # End time in seconds
    confidence: Optional[float] = None


@dataclass
class TranscriptionResult:
    """Result of a speech-to-text transcription."""

    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    duration_seconds: float = 0.0
    segments: List[Segment] = field(default_factory=list)


class SpeechBackend(ABC):
    """Abstract base class for speech-to-text backends."""

    backend_id: str = ""

    @abstractmethod
    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes to text."""

    @abstractmethod
    def health(self) -> bool:
        """Check if the backend is ready."""

    @abstractmethod
    def supported_formats(self) -> List[str]:
        """Return list of supported audio formats."""


__all__ = ["Segment", "SpeechBackend", "TranscriptionResult"]
