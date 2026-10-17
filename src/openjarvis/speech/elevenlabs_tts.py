"""ElevenLabs text-to-speech backend.

Uses the ElevenLabs REST API for high-quality multilingual voice synthesis.
Requires ELEVENLABS_API_KEY environment variable or config.
"""

from __future__ import annotations

import io
import os
import re
import wave
from typing import List

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
    resp = httpx.post(
        f"{_ELEVENLABS_API_BASE}/text-to-speech/{voice_id}",
        params={"output_format": _OUTPUT_FORMATS.get(output_format, "mp3_44100_128")},
        headers={"xi-api-key": api_key},
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
    resp.raise_for_status()
    return resp.content


@TTSRegistry.register("elevenlabs")
class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs TTS backend — premium multilingual synthesis."""

    backend_id = "elevenlabs"

    def __init__(
        self, *, api_key: str = "", model: str = "", voice_id: str = ""
    ) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
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
        resp = httpx.get(
            f"{_ELEVENLABS_API_BASE}/voices",
            headers={"xi-api-key": self._api_key},
            timeout=30.0,
        )
        resp.raise_for_status()
        return [v["voice_id"] for v in resp.json().get("voices", [])]

    def health(self) -> bool:
        return bool(self._api_key)
