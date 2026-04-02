"""Cartesia text-to-speech backend.

Uses the Cartesia REST API for high-quality, low-latency voice synthesis.
Requires CARTESIA_API_KEY environment variable or config.
"""

from __future__ import annotations

import os
from typing import List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_CARTESIA_API_BASE = "https://api.cartesia.ai"


def _cartesia_synthesize(
    api_key: str,
    text: str,
    voice_id: str,
    model: str = "sonic",
    output_format: str = "mp3",
    speed: float = 1.0,
) -> bytes:
    """Call the Cartesia TTS API and return raw audio bytes."""
    resp = httpx.post(
        f"{_CARTESIA_API_BASE}/tts/bytes",
        headers={
            "X-API-Key": api_key,
            "Cartesia-Version": "2024-06-10",
        },
        json={
            "model_id": model,
            "transcript": text,
            "voice": {"mode": "id", "id": voice_id},
            "output_format": {
                "container": output_format,
                "sample_rate": 24000,
                "encoding": "mp3" if output_format == "mp3" else "pcm_f32le",
            },
            "language": "en",
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.content


@TTSRegistry.register("cartesia")
class CartesiaTTSBackend(TTSBackend):
    """Cartesia TTS backend — fast, high-quality synthesis."""

    backend_id = "cartesia"

    def __init__(self, *, api_key: str = "", model: str = "sonic") -> None:
        self._api_key = api_key or os.environ.get("CARTESIA_API_KEY", "")
        self._model = model

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("CARTESIA_API_KEY not set")

        audio = _cartesia_synthesize(
            self._api_key,
            text,
            voice_id=voice_id,
            model=self._model,
            output_format=output_format,
            speed=speed,
        )

        return TTSResult(
            audio=audio,
            format=output_format,
            voice_id=voice_id,
            metadata={"backend": "cartesia", "model": self._model},
        )

    def available_voices(self) -> List[str]:
        if not self._api_key:
            return []
        resp = httpx.get(
            f"{_CARTESIA_API_BASE}/voices",
            headers={
                "X-API-Key": self._api_key,
                "Cartesia-Version": "2024-06-10",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return [v["id"] for v in resp.json()]

    def health(self) -> bool:
        return bool(self._api_key)
