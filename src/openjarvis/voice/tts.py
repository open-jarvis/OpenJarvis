"""Local TTS helpers for Friday app mode."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SAY_PATH = Path("/usr/bin/say")
DEFAULT_TTS_VOICE = "Yuna"
DEFAULT_TTS_RATE = 175
DEFAULT_TTS_MAX_CHARS = 400
MAX_TTS_CHARS = 1200

_CURRENT_SAY_PROCESS: subprocess.Popen | None = None


@dataclass(slots=True)
class SpeakResult:
    ok: bool
    message: str = ""
    engine: str = "macos_say"
    text: str = ""
    chunks: list[str] | None = None


def cleanup_tts_text(text: str, *, max_chars: int = DEFAULT_TTS_MAX_CHARS) -> str:
    """Make assistant text more natural and safer to read aloud."""
    limit = max(1, min(int(max_chars or DEFAULT_TTS_MAX_CHARS), MAX_TTS_CHARS))
    cleaned = text or ""
    cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
    cleaned = re.sub(r"`[^`]+`", " ", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"^\s*[-*•]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(
        r"\b(?:ollama|tokens?|token/sec|cost comparison)\b",
        " ",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"Traceback \(most recent call last\):[\s\S]*", " ", cleaned)
    replacements = {
        "->": "에서",
        "=>": "결과는",
        "&": "그리고",
        "%": "퍼센트",
        "/": " 또는 ",
        "=": " 는 ",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit].strip()


def split_tts_chunks(text: str, *, max_chars: int = 120) -> list[str]:
    """Split Korean text into short sentence chunks."""
    cleaned = text.strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    sentence_parts = re.split(r"(?<=[.!?。！？요다니다죠습니다])\s+", cleaned)
    for sentence in sentence_parts:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            split_at = sentence.rfind(" ", 0, max_chars)
            if split_at <= 0:
                split_at = max_chars
            chunks.append(sentence[:split_at].strip())
            sentence = sentence[split_at:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


def stop_macos_say() -> None:
    global _CURRENT_SAY_PROCESS
    proc = _CURRENT_SAY_PROCESS
    _CURRENT_SAY_PROCESS = None
    if proc and proc.poll() is None:
        proc.terminate()


def speak_macos_say(
    text: str,
    *,
    voice: str = DEFAULT_TTS_VOICE,
    rate: int = DEFAULT_TTS_RATE,
    max_chars: int = DEFAULT_TTS_MAX_CHARS,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SpeakResult:
    """Speak text with macOS /usr/bin/say using safe argv construction."""
    if not SAY_PATH.exists():
        return SpeakResult(
            ok=False,
            message="TTS 음성을 찾을 수 없습니다. macOS 음성 설정을 확인해주세요.",
        )
    cleaned = cleanup_tts_text(text, max_chars=max_chars)
    if not cleaned:
        return SpeakResult(ok=False, message="읽을 음성 응답이 없습니다.")
    chunks = split_tts_chunks(cleaned)
    spoken_text = " ".join(chunks).strip()
    if not spoken_text:
        return SpeakResult(ok=False, message="읽을 음성 응답이 없습니다.")

    stop_macos_say()
    safe_rate = max(80, min(int(rate or DEFAULT_TTS_RATE), 320))
    safe_voice = (voice or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
    command = [str(SAY_PATH), "-v", safe_voice, "-r", str(safe_rate), spoken_text]
    try:
        global _CURRENT_SAY_PROCESS
        _CURRENT_SAY_PROCESS = popen(command)
    except FileNotFoundError:
        return SpeakResult(
            ok=False,
            message="TTS 음성을 찾을 수 없습니다. macOS 음성 설정을 확인해주세요.",
        )
    except OSError as exc:
        return SpeakResult(ok=False, message=f"로컬 TTS 실행에 실패했습니다: {exc}")
    return SpeakResult(
        ok=True,
        message="음성 응답 중...",
        text=spoken_text,
        chunks=chunks,
    )


__all__ = [
    "DEFAULT_TTS_MAX_CHARS",
    "DEFAULT_TTS_RATE",
    "DEFAULT_TTS_VOICE",
    "MAX_TTS_CHARS",
    "SAY_PATH",
    "SpeakResult",
    "cleanup_tts_text",
    "speak_macos_say",
    "split_tts_chunks",
    "stop_macos_say",
]
