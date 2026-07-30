"""Provider boundaries shared by browser, local, and disabled speech modes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SpeechProviderCapabilities:
    """Credential-free provider facts suitable for UI health responses."""

    available: bool
    provider: str
    location: str
    languages: tuple[str, ...] = ("de-DE",)
    degraded: bool = False
    last_error_category: str | None = None


@runtime_checkable
class SpeechToTextProvider(Protocol):
    """Replaceable speech-to-text provider used only before task creation."""

    backend_id: str

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: str | None = None,
    ) -> Any: ...

    def health(self) -> bool: ...


@runtime_checkable
class TextToSpeechProvider(Protocol):
    """Replaceable text-to-speech output provider with no task authority."""

    backend_id: str

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> Any: ...

    def health(self) -> bool: ...


class DisabledSpeechToTextProvider:
    backend_id = "disabled"

    def transcribe(self, audio: bytes, **_: Any) -> Any:
        del audio
        raise RuntimeError("speech_to_text_disabled")

    def health(self) -> bool:
        return False


class DisabledTextToSpeechProvider:
    backend_id = "disabled"

    def synthesize(self, text: str, **_: Any) -> Any:
        del text
        raise RuntimeError("text_to_speech_disabled")

    def health(self) -> bool:
        return False


__all__ = [
    "DisabledSpeechToTextProvider",
    "DisabledTextToSpeechProvider",
    "SpeechProviderCapabilities",
    "SpeechToTextProvider",
    "TextToSpeechProvider",
]
