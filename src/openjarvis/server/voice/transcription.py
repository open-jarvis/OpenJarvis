"""Gemini Live transcription settings for OpenJarvis Voice."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib
from google.genai.types import (
    AudioTranscriptionConfig,
    AudioTranscriptionConfigMode,
)
from pipecat.services.google.gemini_live.stt import GeminiSTTService

DEFAULT_LANGUAGE_CODES = ("vi-VN", "en-US")
DEFAULT_TRANSCRIPTION_MODE = AudioTranscriptionConfigMode.VERBATIM
MAX_CUSTOM_VOCABULARY_TERMS = 1_000


@dataclass(frozen=True)
class GeminiSTTProfile:
    """The part of a Gemini Live request that improves recognition accuracy."""

    language_codes: tuple[str, ...] = DEFAULT_LANGUAGE_CODES
    custom_vocabulary: tuple[str, ...] = ()
    mode: AudioTranscriptionConfigMode = DEFAULT_TRANSCRIPTION_MODE


def _string_list(
    section: Mapping[str, Any], key: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    value = section.get(key)
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"voice_stt_{key}_must_be_a_string_list")

    cleaned = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
    if key == "custom_vocabulary" and len(cleaned) > MAX_CUSTOM_VOCABULARY_TERMS:
        raise ValueError("voice_stt_custom_vocabulary_too_large")
    return cleaned


def load_gemini_stt_profile() -> GeminiSTTProfile:
    """Load optional ``[voice.stt]`` settings from the active preset."""
    config_value = os.environ.get("OPENJARVIS_CONFIG", "").strip()
    if not config_value:
        return GeminiSTTProfile()

    config_path = Path(config_value).expanduser()
    if not config_path.exists():
        return GeminiSTTProfile()
    with config_path.open("rb") as config_file:
        data = tomllib.load(config_file)

    voice = data.get("voice", {})
    if not isinstance(voice, Mapping):
        raise ValueError("voice_config_must_be_a_table")
    section = voice.get("stt", {})
    if not isinstance(section, Mapping):
        raise ValueError("voice_stt_config_must_be_a_table")

    language_codes = _string_list(
        section, "language_codes", DEFAULT_LANGUAGE_CODES
    )
    custom_vocabulary = _string_list(section, "custom_vocabulary", ())
    raw_mode = section.get("mode", DEFAULT_TRANSCRIPTION_MODE.value)
    if not isinstance(raw_mode, str):
        raise ValueError("voice_stt_mode_must_be_a_string")
    try:
        mode = AudioTranscriptionConfigMode(raw_mode.strip().upper())
    except ValueError as exc:
        raise ValueError("voice_stt_mode_must_be_verbatim_or_smart") from exc
    if mode is AudioTranscriptionConfigMode.MODE_UNSPECIFIED:
        raise ValueError("voice_stt_mode_must_be_verbatim_or_smart")

    return GeminiSTTProfile(
        language_codes=language_codes,
        custom_vocabulary=custom_vocabulary,
        mode=mode,
    )


class OpenJarvisGeminiSTTService(GeminiSTTService):
    """Use current Gemini transcription fields missing from Pipecat 1.8.1."""

    def __init__(self, *, profile: GeminiSTTProfile, **kwargs: Any) -> None:
        self._openjarvis_profile = profile
        super().__init__(**kwargs)

    def _build_live_config(self):
        config = super()._build_live_config()
        profile = self._openjarvis_profile
        config.input_audio_transcription = AudioTranscriptionConfig(
            language_codes=list(profile.language_codes),
            custom_vocabulary=list(profile.custom_vocabulary) or None,
            mode=profile.mode,
        )
        return config


__all__ = [
    "GeminiSTTProfile",
    "OpenJarvisGeminiSTTService",
    "load_gemini_stt_profile",
]
