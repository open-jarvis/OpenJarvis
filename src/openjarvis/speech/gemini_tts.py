"""Gemini text-to-speech backend.

Uses the Gemini API TTS endpoint and returns WAV audio.
Requires GEMINI_API_KEY or GOOGLE_API_KEY.
"""

from __future__ import annotations

import base64
import io
import os
import wave
from typing import List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
_DEFAULT_VOICE = "Orus"
_SAMPLE_RATE = 24000
_SAMPLE_WIDTH = 2
_CHANNELS = 1

_DEFAULT_STYLE_PROMPT = """Read the transcript as a calm AI assistant voice.
Voice profile: low, firm, controlled, precise, polished, warm, and quietly witty.
Accent: polished British when speaking English; clear neutral pronunciation when speaking German.
Pacing: measured and unhurried, with short natural pauses between sentences.
Important: do not add, omit, translate, or paraphrase words. Speak only the transcript."""

_VOICES = [
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
]


def _pcm_to_wav(pcm: bytes) -> bytes:
    """Wrap Gemini's 24 kHz 16-bit mono PCM payload in a WAV container."""
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(pcm)
    return out.getvalue()


def _style_prompt(text: str, speed: float) -> str:
    speed_hint = ""
    if speed < 0.95:
        speed_hint = "\nDelivery speed: a little slower than normal."
    elif speed > 1.05:
        speed_hint = "\nDelivery speed: a little faster than normal."

    return f"{_DEFAULT_STYLE_PROMPT}{speed_hint}\n\nTRANSCRIPT:\n{text}"


def _gemini_tts_request(
    api_key: str,
    text: str,
    voice_name: str,
    model: str,
    speed: float,
) -> bytes:
    """Call the Gemini TTS API and return WAV audio bytes."""
    response = httpx.post(
        f"{_GEMINI_API_BASE}/models/{model}:generateContent",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        json={
            "contents": [
                {
                    "parts": [
                        {
                            "text": _style_prompt(text, speed),
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice_name,
                        }
                    }
                },
            },
        },
        timeout=120.0,
    )
    response.raise_for_status()

    payload = response.json()
    try:
        inline_data = payload["candidates"][0]["content"]["parts"][0]["inlineData"]
        pcm = base64.b64decode(inline_data["data"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini TTS response did not contain audio data") from exc

    return _pcm_to_wav(pcm)


@TTSRegistry.register("gemini_tts")
class GeminiTTSBackend(TTSBackend):
    """Gemini TTS backend for controllable external voice synthesis."""

    backend_id = "gemini_tts"

    def __init__(self, *, api_key: str = "", model: str = "") -> None:
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY", "")
            or os.environ.get("GOOGLE_API_KEY", "")
        )
        self._model = model or os.environ.get("GEMINI_TTS_MODEL", _DEFAULT_MODEL)

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY not set")

        voice_name = voice_id or _DEFAULT_VOICE
        audio = _gemini_tts_request(
            self._api_key,
            text,
            voice_name=voice_name,
            model=self._model,
            speed=speed,
        )

        return TTSResult(
            audio=audio,
            format="wav",
            voice_id=voice_name,
            sample_rate=_SAMPLE_RATE,
            metadata={"backend": "gemini_tts", "model": self._model},
        )

    def available_voices(self) -> List[str]:
        return list(_VOICES)

    def health(self) -> bool:
        return bool(self._api_key)
