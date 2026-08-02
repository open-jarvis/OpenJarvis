"""Persistent, secret-free configuration for the local JARVIS voice."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

AUDITION_TEXT = (
    "Guten Abend, Deaa. Alle Systeme sind betriebsbereit. Ich habe deine "
    "aktuellen Aufgaben analysiert und bin bereit, sie auszuführen."
)


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    voice_id: str
    number: int
    label: str
    backend: str
    pitch_semitones: float
    speed: float
    exaggeration: float
    cfg_weight: float
    temperature: float
    seed: int
    description: str


VOICE_PROFILES = (
    VoiceProfile(
        "jarvis-deep-calm",
        1,
        "Tief und ruhig",
        "chatterbox",
        -3.0,
        0.92,
        0.32,
        0.55,
        0.72,
        104729,
        "Tiefe, ruhige Hauptvariante mit kontrollierter Dynamik.",
    ),
    VoiceProfile(
        "jarvis-deep-clear",
        2,
        "Tief und klar",
        "chatterbox",
        -2.2,
        0.96,
        0.36,
        0.52,
        0.70,
        130363,
        "Etwas schneller, mit besonders klarer deutscher Artikulation.",
    ),
    VoiceProfile(
        "jarvis-sovereign",
        3,
        "Souverän",
        "chatterbox",
        -3.8,
        0.90,
        0.38,
        0.58,
        0.68,
        155921,
        "Die tiefste, bewusst gemessene Variante mit wenig Emotion.",
    ),
    VoiceProfile(
        "jarvis-balanced",
        4,
        "Ausgewogen",
        "chatterbox",
        -1.6,
        0.98,
        0.40,
        0.50,
        0.74,
        180503,
        "Natürlichere Tonhöhe bei weiterhin ruhigem JARVIS-Charakter.",
    ),
    VoiceProfile(
        "jarvis-piper-fast",
        5,
        "Schneller Fallback",
        "piper",
        -1.4,
        0.96,
        0.0,
        0.0,
        0.0,
        0,
        "Schnelle lokale CPU-Stimme für Fehler- und Niedriglatenzfälle.",
    ),
)

PROFILE_BY_ID = {profile.voice_id: profile for profile in VOICE_PROFILES}
DEFAULT_VOICE_ID = VOICE_PROFILES[0].voice_id


def public_profile(profile: VoiceProfile) -> dict[str, Any]:
    """Return the non-sensitive settings displayed by the audition UI."""

    return asdict(profile)


def default_voice_config() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "selected_voice_id": DEFAULT_VOICE_ID,
        "primary_backend": "chatterbox",
        "fallback_backend": "piper",
        "language": "de",
        "sentence_streaming": True,
        "cache_enabled": True,
        "voice_reference": None,
    }


def load_voice_config(path: Path) -> dict[str, Any]:
    """Load a validated config or create the deterministic default atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        write_voice_config(path, default_voice_config())
    data = json.loads(path.read_text(encoding="utf-8"))
    selected = str(data.get("selected_voice_id", ""))
    if selected not in PROFILE_BY_ID:
        raise ValueError("voice config contains an unknown voice profile")
    if data.get("voice_reference") is not None:
        raise ValueError("voice cloning references are disabled")
    return {**default_voice_config(), **data, "selected_voice_id": selected}


def write_voice_config(path: Path, data: dict[str, Any]) -> None:
    """Persist non-secret settings with replace-on-success semantics."""

    selected = str(data.get("selected_voice_id", ""))
    if selected not in PROFILE_BY_ID:
        raise ValueError("unknown voice profile")
    if data.get("voice_reference") is not None:
        raise ValueError("voice cloning references are disabled")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "AUDITION_TEXT",
    "DEFAULT_VOICE_ID",
    "PROFILE_BY_ID",
    "VOICE_PROFILES",
    "VoiceProfile",
    "default_voice_config",
    "load_voice_config",
    "public_profile",
    "write_voice_config",
]
