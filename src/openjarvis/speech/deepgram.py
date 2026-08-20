"""Deepgram speech-to-text backend (cloud)."""

from __future__ import annotations

import os
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import SpeechBackend, TranscriptionResult

try:
    from deepgram import DeepgramClient, PrerecordedOptions
except ImportError:
    DeepgramClient = None  # type: ignore[assignment, misc]
    PrerecordedOptions = None  # type: ignore[assignment, misc]


@SpeechRegistry.register("deepgram")
class DeepgramSpeechBackend(SpeechBackend):
    """Cloud speech-to-text using Deepgram API."""

    backend_id = "deepgram"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.environ.get("DEEPGRAM_API_KEY", "")
        self._client = None
        if self._api_key and DeepgramClient is not None:
            self._client = DeepgramClient(self._api_key)

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using Deepgram's API."""
        if self._client is None:
            raise RuntimeError("Deepgram client not initialized (missing API key?)")

        mime_map = {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
            "webm": "audio/webm",
            "m4a": "audio/mp4",
        }
        mime_type = mime_map.get(format, "audio/wav")

        options_kwargs: dict = {"model": "nova-2", "smart_format": True}
        if language:
            options_kwargs["language"] = language
        else:
            options_kwargs["detect_language"] = True

        payload = {"buffer": audio, "mimetype": mime_type}

        if PrerecordedOptions is not None:
            options = PrerecordedOptions(**options_kwargs)
        else:
            options = options_kwargs

        response = self._client.listen.rest.v("1").transcribe_file(
            payload,
            options,
        )

        # Extract transcript from response
        channels = response.results.channels
        if channels and channels[0].alternatives:
            alt = channels[0].alternatives[0]
            text = alt.transcript
            confidence = getattr(alt, "confidence", None)
        else:
            text = ""
            confidence = None

        detected_lang = None
        if channels:
            detected_lang = getattr(channels[0], "detected_language", None)

        duration = getattr(response.metadata, "duration", 0.0)

        return TranscriptionResult(
            text=text,
            language=detected_lang,
            confidence=confidence,
            duration_seconds=duration,
            segments=[],
        )

    def health(self) -> bool:
        return self._client is not None and bool(self._api_key)

    def supported_formats(self) -> List[str]:
        return ["wav", "mp3", "ogg", "flac", "webm", "m4a"]
