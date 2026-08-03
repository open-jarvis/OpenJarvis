"""Persistent, secret-free configuration for the local JARVIS voice."""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, BinaryIO, Iterator

AUDITION_TEXT = (
    "Guten Abend. Alle Systeme sind betriebsbereit. Ich habe deine "
    "aktuellen Aufgaben analysiert und bin bereit, sie auszuführen."
)

# Bump this whenever conditioning or audio rendering changes. Existing WAV files
# are accepted only when their adjacent metadata carries this exact value.
VOICE_CACHE_SCHEMA = "voice-v11-elevenlabs-hybrid"

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

LEGACY_VOICE_ALIASES: dict[str, str] = {"jarvis-sovereign": "jarvis-deep-calm"}

# ---------------------------------------------------------------------------
# Cost control defaults for ElevenLabs
# ---------------------------------------------------------------------------
DEFAULT_MONTHLY_CHAR_LIMIT = 100_000
DEFAULT_PER_RESPONSE_CHAR_LIMIT = 4_000
DEFAULT_LOCAL_FALLBACK_VOICE_ID = "jarvis-deep-calm"

_USAGE_LOCKS_GUARD = threading.Lock()
_USAGE_LOCKS: dict[Path, threading.Lock] = {}


class ElevenLabsUsageLimit(RuntimeError):
    """Raised before a paid request when a configured local guard is exhausted."""


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
        "jarvis-elevenlabs",
        1,
        "ElevenLabs – konfigurierbare Stimme",
        "elevenlabs",
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0,
        "Natürliche deutsche Stimme über ElevenLabs API. Erfordert API-Key und Voice-ID.",
    ),
    VoiceProfile(
        "jarvis-deep-calm",
        2,
        "Chatterbox – Lokal/Offline",
        "chatterbox",
        0.0,
        1.0,
        0.38,
        0.52,
        0.72,
        104729,
        "Lokale neuronale Stimme auf GPU. Offline-Fallback wenn ElevenLabs nicht verfügbar.",
    ),
    VoiceProfile(
        "jarvis-deep-clear",
        3,
        "Chatterbox – Tief und klar",
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
        4,
        "Chatterbox – Ausgewogen",
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
        5,
        "Piper – Notfallstimme",
        "piper",
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0,
        "Schnelle synthetische CPU-Stimme. Letzter technischer Notfall.",
    ),
)

PROFILE_BY_ID = {profile.voice_id: profile for profile in VOICE_PROFILES}
DEFAULT_VOICE_ID = "jarvis-elevenlabs"


def public_profile(profile: VoiceProfile) -> dict[str, Any]:
    """Return the non-sensitive settings displayed by the audition UI."""

    return asdict(profile)


def default_voice_config() -> dict[str, Any]:
    return {
        "schema_version": "3.0",
        "selected_voice_id": DEFAULT_VOICE_ID,
        "primary_backend": "elevenlabs",
        "local_fallback_backend": "chatterbox",
        "emergency_backend": "piper",
        "language": "de",
        "sentence_streaming": True,
        "cache_enabled": True,
        "voice_reference": None,
        "local_fallback_voice_id": DEFAULT_LOCAL_FALLBACK_VOICE_ID,
        "elevenlabs_voice_id": None,
        "elevenlabs_model_id": "eleven_flash_v2_5",
        "monthly_char_limit": DEFAULT_MONTHLY_CHAR_LIMIT,
        "per_response_char_limit": DEFAULT_PER_RESPONSE_CHAR_LIMIT,
    }


def load_voice_config(path: Path) -> dict[str, Any]:
    """Load a validated config or create the deterministic default atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        write_voice_config(path, default_voice_config())
    data = json.loads(path.read_text(encoding="utf-8"))
    # Migrate the Phase-6 two-backend key without discarding user choices.
    migrated = False
    if "fallback_backend" in data:
        data.setdefault("local_fallback_backend", "chatterbox")
        data.setdefault("emergency_backend", str(data.pop("fallback_backend")))
        migrated = True
    selected = str(data.get("selected_voice_id", ""))
    if selected in LEGACY_VOICE_ALIASES:
        selected = LEGACY_VOICE_ALIASES[selected]
        data["selected_voice_id"] = selected
        migrated = True
    if selected not in PROFILE_BY_ID:
        raise ValueError("voice config contains an unknown voice profile")
    if data.get("voice_reference") is not None:
        raise ValueError("voice cloning references are disabled")
    merged = {**default_voice_config(), **data, "selected_voice_id": selected}
    selected_backend = PROFILE_BY_ID[selected].backend
    if merged.get("primary_backend") != selected_backend:
        merged["primary_backend"] = selected_backend
        migrated = True
    fallback_voice = str(merged.get("local_fallback_voice_id", ""))
    fallback_profile = PROFILE_BY_ID.get(fallback_voice)
    if fallback_profile is None or fallback_profile.backend != "chatterbox":
        raise ValueError("local fallback voice must be a Chatterbox profile")
    if merged.get("primary_backend") not in {"elevenlabs", "chatterbox", "piper"}:
        raise ValueError("voice config contains an invalid primary backend")
    if merged.get("local_fallback_backend") != "chatterbox":
        raise ValueError("local fallback backend must be chatterbox")
    if merged.get("emergency_backend") != "piper":
        raise ValueError("emergency backend must be piper")
    voice_id = merged.get("elevenlabs_voice_id")
    if voice_id is not None and (not isinstance(voice_id, str) or not voice_id.strip()):
        raise ValueError("ElevenLabs voice ID must be a non-empty string or null")
    for key, default in (
        ("monthly_char_limit", DEFAULT_MONTHLY_CHAR_LIMIT),
        ("per_response_char_limit", DEFAULT_PER_RESPONSE_CHAR_LIMIT),
    ):
        try:
            merged[key] = max(0, int(merged.get(key, default)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be an integer") from exc
    if migrated:
        write_voice_config(path, merged)
    return merged


def write_voice_config(path: Path, data: dict[str, Any]) -> None:
    """Persist non-secret settings with replace-on-success semantics."""

    selected = str(data.get("selected_voice_id", ""))
    if selected not in PROFILE_BY_ID:
        raise ValueError("unknown voice profile")
    if data.get("voice_reference") is not None:
        raise ValueError("voice cloning references are disabled")
    safe_data = {**default_voice_config(), **data}
    safe_data.pop("fallback_backend", None)
    safe_data["primary_backend"] = PROFILE_BY_ID[selected].backend
    safe_data["local_fallback_backend"] = "chatterbox"
    safe_data["emergency_backend"] = "piper"
    if any("api_key" in str(key).lower() for key in safe_data):
        raise ValueError("voice config must never contain API keys")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(safe_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# ElevenLabs monthly usage tracking
# ---------------------------------------------------------------------------

def _usage_path(voice_root: Path) -> Path:
    return voice_root / "elevenlabs-usage.json"


def load_elevenlabs_usage(voice_root: Path) -> dict[str, Any]:
    """Load the local ElevenLabs character usage tracker."""
    path = _usage_path(voice_root)
    current_month = date.today().strftime("%Y-%m")
    default: dict[str, Any] = {"month": current_month, "characters_used": 0}
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("month") != current_month:
            return default
        return data
    except (json.JSONDecodeError, OSError):
        return default


@contextmanager
def _locked_usage_file(voice_root: Path) -> Iterator[None]:
    """Serialize reservations across threads and processes on Windows/POSIX."""

    root = voice_root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "elevenlabs-usage.lock"
    with _USAGE_LOCKS_GUARD:
        thread_lock = _USAGE_LOCKS.setdefault(lock_path, threading.Lock())
    with thread_lock:
        with lock_path.open("a+b") as handle:
            _lock_file(handle)
            try:
                yield
            finally:
                _unlock_file(handle)


def _lock_file(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_elevenlabs_usage(voice_root: Path, usage: dict[str, Any]) -> None:
    path = _usage_path(voice_root)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(
        json.dumps(usage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def reserve_elevenlabs_usage(
    voice_root: Path,
    characters: int,
    *,
    monthly_limit: int,
) -> dict[str, Any]:
    """Reserve estimated characters atomically before a paid API request."""

    requested = max(0, int(characters))
    with _locked_usage_file(voice_root):
        usage = load_elevenlabs_usage(voice_root)
        current = max(0, int(usage.get("characters_used", 0)))
        if monthly_limit <= 0 or current + requested > monthly_limit:
            raise ElevenLabsUsageLimit("ElevenLabsMonthlyLimitReached")
        usage["characters_used"] = current + requested
        _write_elevenlabs_usage(voice_root, usage)
        return usage


def record_elevenlabs_usage(voice_root: Path, characters: int) -> dict[str, Any]:
    """Compatibility helper for callers without an explicit monthly limit."""

    return reserve_elevenlabs_usage(
        voice_root,
        characters,
        monthly_limit=2**63 - 1,
    )


__all__ = [
    "AUDITION_TEXT",
    "DEFAULT_LOCAL_FALLBACK_VOICE_ID",
    "DEFAULT_MONTHLY_CHAR_LIMIT",
    "DEFAULT_PER_RESPONSE_CHAR_LIMIT",
    "DEFAULT_VOICE_ID",
    "ElevenLabsUsageLimit",
    "LEGACY_VOICE_ALIASES",
    "PROFILE_BY_ID",
    "VOICE_CACHE_SCHEMA",
    "VOICE_PROFILES",
    "VOICE_REFERENCE_ASSETS",
    "VoiceProfile",
    "default_voice_config",
    "load_elevenlabs_usage",
    "load_voice_config",
    "public_profile",
    "record_elevenlabs_usage",
    "reserve_elevenlabs_usage",
    "write_voice_config",
]
