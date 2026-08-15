"""Provider-neutral realtime speech contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

AudioEncoding = Literal["pcm_s16le", "ogg_opus", "audio/mpeg"]
RealtimeTtsProvider = Literal["local"]
RealtimeSpeechEventKind = Literal[
    "user_transcript_partial",
    "user_transcript_final",
    "assistant_transcript_partial",
    "assistant_transcript_final",
    "assistant_audio",
    "assistant_turn_complete",
    "recoverable_error",
]


@dataclass(frozen=True, slots=True)
class RealtimeSpeechInput:
    """One transient microphone PCM frame."""

    audio: bytes
    sample_rate_hz: int = 16_000
    channels: int = 1

    def __post_init__(self) -> None:
        if not self.audio:
            raise ValueError("audio_required")
        if self.sample_rate_hz <= 0 or self.channels != 1:
            raise ValueError("mono_pcm_required")


@dataclass(frozen=True, slots=True)
class RealtimeSpeechEvent:
    """One ordered, transient provider event."""

    kind: RealtimeSpeechEventKind
    text: str | None = None
    audio: bytes | None = None

    def __post_init__(self) -> None:
        if self.text is None and self.audio is None:
            raise ValueError("speech_event_payload_required")


@dataclass(frozen=True, slots=True)
class RealtimeTtsChunk:
    """One ordered, transient assistant audio frame."""

    audio: bytes
    provider: RealtimeTtsProvider
    encoding: AudioEncoding
    sample_rate_hz: int
    channels: int
    caption: str | None = None

    def __post_init__(self) -> None:
        if not self.audio:
            raise ValueError("audio_required")
        if self.provider != "local":
            raise ValueError("local_tts_provider_required")
        if (
            self.encoding != "pcm_s16le"
            or self.sample_rate_hz != 48_000
            or self.channels != 1
        ):
            raise ValueError("local_tts_requires_mono_48khz_pcm_s16le")


class RealtimeTts(Protocol):
    """Streams audio for one complete OpenJarvis-produced assistant turn."""

    def stream_tts(self, text: str) -> AsyncIterator[RealtimeTtsChunk]: ...


class RealtimeSpeechAdapter(Protocol):
    """Bidirectional, provider-neutral realtime speech session."""

    async def start(self) -> None: ...

    async def send_pcm(self, frame: RealtimeSpeechInput) -> None: ...

    async def finish_input(self) -> None: ...

    def events(self) -> AsyncIterator[RealtimeSpeechEvent]: ...

    async def interrupt_output(self) -> None:
        """Stop current assistant output while preserving live input events."""
        ...

    async def cancel(self) -> None: ...

    async def close(self) -> None: ...


__all__ = [
    "AudioEncoding",
    "RealtimeSpeechAdapter",
    "RealtimeSpeechEvent",
    "RealtimeSpeechEventKind",
    "RealtimeSpeechInput",
    "RealtimeTts",
    "RealtimeTtsChunk",
    "RealtimeTtsProvider",
]
