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

# Bump this whenever conditioning or audio rendering changes. Existing WAV files
# are accepted only when their adjacent metadata carries this exact value.
VOICE_CACHE_SCHEMA = "voice-v8-synthetic-reference-natural"

# The files are machine-generated, non-human reference voices. Hash allowlisting
# prevents a runtime file from silently turning this into arbitrary voice cloning.
VOICE_REFERENCE_ASSETS: dict[str, tuple[str, str]] = {
    "jarvis-deep-calm": (
        "jarvis-deep-calm.wav",
        "1430fded8455dfd660535bde48ae287963ae3f12ac0823dfe7468b376a367be2",
    ),
    "jarvis-deep-clear": (
        "jarvis-deep-clear.wav",
        "0c2297327f4354223ad6c94712e2302e399ca84f395884f9b97368840bd127ac",
    ),
    "jarvis-balanced": (
        "jarvis-balanced.wav",
        "6ef312e4754e441a3715b8c80ba12b6bad96a0d2e1c821eea67977d10ba1bb2a",
    ),
}

LEGACY_VOICE_ALIASES = {"jarvis-sovereign": "jarvis-deep-calm"}


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
        0.0,
        1.0,
        0.38,
        0.52,
        0.72,
        104729,
        "Ruhiges neuronales Stimmprofil mit eigenem natürlichem Timbre.",
    ),
    VoiceProfile(
        "jarvis-deep-clear",
        2,
        "Tief und klar",
        "chatterbox",
        0.0,
        1.0,
        0.42,
        0.48,
        0.70,
        130363,
        "Klares neuronales Stimmprofil mit präziser deutscher Artikulation.",
    ),
    VoiceProfile(
        "jarvis-balanced",
        3,
        "Ausgewogen",
        "chatterbox",
        0.0,
        1.0,
        0.34,
        0.56,
        0.68,
        180503,
        "Ausgewogenes neuronales Stimmprofil mit natürlicher Sprechlage.",
    ),
    VoiceProfile(
        "jarvis-piper-fast",
        4,
        "Notfallstimme (schnell)",
        "piper",
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0,
        "Schnelle synthetische CPU-Stimme, nur als technischer Fallback.",
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
    if selected in LEGACY_VOICE_ALIASES:
        selected = LEGACY_VOICE_ALIASES[selected]
        data["selected_voice_id"] = selected
        write_voice_config(path, {**default_voice_config(), **data})
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
    "LEGACY_VOICE_ALIASES",
    "PROFILE_BY_ID",
    "VOICE_CACHE_SCHEMA",
    "VOICE_PROFILES",
    "VOICE_REFERENCE_ASSETS",
    "VoiceProfile",
    "default_voice_config",
    "load_voice_config",
    "public_profile",
    "write_voice_config",
]
