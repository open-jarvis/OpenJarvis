"""Abstract base classes and data types for text-to-speech backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class TTSResult:
    """Result of a text-to-speech synthesis."""

    audio: bytes
    format: str = "mp3"
    duration_seconds: float = 0.0
    voice_id: str = ""
    sample_rate: int = 24000
    metadata: Dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> Path:
        """Write audio bytes to a file and return the path."""
        path.write_bytes(self.audio)
        return path


class TTSBackend(ABC):
    """Abstract base class for text-to-speech backends."""

    backend_id: str = ""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        """Synthesize text to audio."""

    @abstractmethod
    def available_voices(self) -> List[str]:
        """Return list of available voice IDs."""

    @abstractmethod
    def health(self) -> bool:
        """Check if the backend is ready."""


__all__ = ["TTSBackend", "TTSResult"]
