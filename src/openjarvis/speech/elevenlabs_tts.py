"""ElevenLabs text-to-speech backend.

Uses the ElevenLabs REST API for high-quality multilingual voice synthesis.
Requires ELEVENLABS_API_KEY environment variable or config.
"""

from __future__ import annotations

import io
import os
import re
import wave
from collections.abc import Callable
from typing import Any, List, TypeVar

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

# "George" — warm British male premade voice, Jarvis-like
_DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"

# Kokoro-style IDs ("bm_george", "pf_dora"). SpeechConfig.voice_id defaults to
# a Kokoro voice, so it can reach this backend; ElevenLabs would 404 on it.
_KOKORO_VOICE_RE = re.compile(r"^[a-z][fm]_[a-z]+$")

_PCM_SAMPLE_RATE = 24000
_OUTPUT_FORMATS = {
    "mp3": "mp3_44100_128",
    "pcm": f"pcm_{_PCM_SAMPLE_RATE}",
    "wav": f"pcm_{_PCM_SAMPLE_RATE}",  # wrapped in a WAV header locally
}
_ResponseT = TypeVar("_ResponseT")


def _normalize_api_key(value: str) -> str:
    key = value.strip()
    if any(not 33 <= ord(char) <= 126 for char in key):
        # Reject unsupported header characters without echoing the credential.
        raise ValueError("ElevenLabs API key contains unsupported characters")
    return key


def _request(
    request: Callable[..., httpx.Response],
    path: str,
    api_key: str,
    read_response: Callable[[httpx.Response], _ResponseT],
    **kwargs: Any,
) -> _ResponseT:
    """Keep provider request/response details out of errors and their tracebacks."""
    key = _normalize_api_key(api_key)
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    try:
        response = request(
            f"{_ELEVENLABS_API_BASE}{path}",
            headers={"xi-api-key": key},
            **kwargs,
        )
        response.raise_for_status()
        # Reading audio/JSON belongs inside the same boundary as sending:
        # transport and decode errors can contain credential-bearing details.
        return read_response(response)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"ElevenLabs request failed (HTTP {exc.response.status_code})"
        ) from None
    except Exception as exc:
        # Preserve the error category, never its message, headers, URL, or body.
        raise RuntimeError(
            f"ElevenLabs request failed ({type(exc).__name__})"
        ) from None


def _voice_ids(response: httpx.Response) -> List[str]:
    payload = response.json()
    voices = payload.get("voices", []) if isinstance(payload, dict) else None
    if not isinstance(voices, list) or any(
        not isinstance(voice, dict) or not isinstance(voice.get("voice_id"), str)
        for voice in voices
    ):
        raise ValueError("Invalid voice list")
    return [voice["voice_id"] for voice in voices]


def _pcm_to_wav(pcm: bytes, sample_rate: int = _PCM_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _elevenlabs_synthesize(
    api_key: str,
    text: str,
    voice_id: str,
    model: str = "eleven_multilingual_v2",
    output_format: str = "mp3",
    speed: float = 1.0,
) -> bytes:
    """Call the ElevenLabs TTS API and return raw audio bytes."""
    return _request(
        httpx.post,
        f"/text-to-speech/{voice_id}",
        api_key,
        lambda response: response.content,
        params={"output_format": _OUTPUT_FORMATS.get(output_format, "mp3_44100_128")},
        json={
            "text": text,
            "model_id": model,
            # ElevenLabs accepts speed in [0.7, 1.2]
            **(
                {"voice_settings": {"speed": max(0.7, min(1.2, speed))}}
                if speed != 1.0
                else {}
            ),
        },
        timeout=120.0,
    )


@TTSRegistry.register("elevenlabs")
class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs TTS backend — premium multilingual synthesis."""

    backend_id = "elevenlabs"

    def __init__(
        self, *, api_key: str = "", model: str = "", voice_id: str = ""
    ) -> None:
        self._api_key = _normalize_api_key(
            api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        )
        self._model = model or os.environ.get(
            "ELEVENLABS_MODEL", "eleven_multilingual_v2"
        )
        self._voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "")

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        if _KOKORO_VOICE_RE.match(voice_id):
            voice_id = ""
        voice_id = voice_id or self._voice_id or _DEFAULT_VOICE_ID
        fmt = output_format if output_format in _OUTPUT_FORMATS else "mp3"

        audio = _elevenlabs_synthesize(
            self._api_key,
            text,
            voice_id=voice_id,
            model=self._model,
            output_format=fmt,
            speed=speed,
        )
        if fmt == "wav":
            audio = _pcm_to_wav(audio)

        return TTSResult(
            audio=audio,
            format=fmt,
            voice_id=voice_id,
            sample_rate=_PCM_SAMPLE_RATE if fmt != "mp3" else 44100,
            metadata={"backend": "elevenlabs", "model": self._model},
        )

    def available_voices(self) -> List[str]:
        if not self._api_key:
            return []
        return _request(
            httpx.get,
            "/voices",
            self._api_key,
            _voice_ids,
            timeout=30.0,
        )

    def health(self) -> bool:
        return bool(self._api_key)
