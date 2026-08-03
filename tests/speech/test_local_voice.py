from __future__ import annotations

import hashlib
import io
import json
import queue
from pathlib import Path
from typing import Any

import pytest

from openjarvis.speech.local_voice import LocalVoiceBackend, VoiceWorkerTimeout
from openjarvis.speech.voice_config import (
    AUDITION_TEXT,
    DEFAULT_VOICE_ID,
    LEGACY_VOICE_ALIASES,
    PROFILE_BY_ID,
    VOICE_CACHE_SCHEMA,
    VOICE_REFERENCE_ASSETS,
    load_voice_config,
    write_voice_config,
)


class _NonClosingStringIO(io.StringIO):
    def close(self) -> None:
        self.flush()


class _HungWorkerProcess:
    def __init__(self) -> None:
        self.stdin = _NonClosingStringIO()
        self.stdout = _NonClosingStringIO()
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1

    def kill(self) -> None:
        self.killed = True
        self.returncode = 1

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            raise TimeoutError
        return self.returncode


def _backend(tmp_path: Path) -> LocalVoiceBackend:
    return LocalVoiceBackend(
        tmp_path,
        worker_python=tmp_path / "python.exe",
        repo_root=tmp_path,
        health_timeout_seconds=0.01,
        synthesis_timeout_seconds=0.01,
        fallback_timeout_seconds=0.01,
    )


def test_voice_config_is_secret_free_persistent_and_rejects_references(
    tmp_path: Path,
) -> None:
    path = tmp_path / "voice" / "voice-config.json"
    config = load_voice_config(path)
    assert config["selected_voice_id"] == DEFAULT_VOICE_ID
    assert config["voice_reference"] is None
    assert AUDITION_TEXT.startswith("Guten Abend.")

    config["selected_voice_id"] = "jarvis-piper-fast"
    write_voice_config(path, config)
    assert load_voice_config(path)["selected_voice_id"] == "jarvis-piper-fast"
    serialized = path.read_text(encoding="utf-8").lower()
    assert "api_key" not in serialized
    assert "token" not in serialized
    assert "password" not in serialized

    config["voice_reference"] = "someone.wav"
    with pytest.raises(ValueError, match="cloning references"):
        write_voice_config(path, config)


def test_profiles_are_numbered_unique_and_have_local_fallback() -> None:
    profiles = list(PROFILE_BY_ID.values())
    assert [profile.number for profile in profiles] == [1, 2, 3, 4, 5]
    assert len({profile.voice_id for profile in profiles}) == len(profiles)
    assert profiles[0].backend == "elevenlabs"
    assert any(profile.backend == "piper" for profile in profiles)
    assert all(profile.pitch_semitones == 0 for profile in profiles)
    assert all(profile.speed == 1 for profile in profiles)
    chatterbox_profiles = [
        profile for profile in profiles if profile.backend == "chatterbox"
    ]
    assert len({profile.seed for profile in chatterbox_profiles}) == 3
    assert all(profile.seed > 0 for profile in chatterbox_profiles)
    assert {profile.voice_id for profile in chatterbox_profiles} == set(
        VOICE_REFERENCE_ASSETS
    )


def test_synthetic_reference_assets_match_the_allowlisted_hashes() -> None:
    reference_root = (
        Path(__file__).resolve().parents[2] / "configs" / "voice" / "references"
    )
    for filename, expected_sha256 in VOICE_REFERENCE_ASSETS.values():
        asset = reference_root / filename
        assert asset.is_file()
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == expected_sha256


def test_legacy_sovereign_selection_migrates_to_a_natural_profile(
    tmp_path: Path,
) -> None:
    path = tmp_path / "voice-config.json"
    config = load_voice_config(path)
    config["selected_voice_id"] = "jarvis-sovereign"
    path.write_text(json.dumps(config), encoding="utf-8")

    migrated = load_voice_config(path)

    assert migrated["selected_voice_id"] == LEGACY_VOICE_ALIASES["jarvis-sovereign"]
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["selected_voice_id"] == migrated["selected_voice_id"]


def test_config_manifest_never_contains_audio_or_reference_data(tmp_path: Path) -> None:
    path = tmp_path / "voice-config.json"
    config = load_voice_config(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == config
    assert set(raw) == {
        "cache_enabled",
        "elevenlabs_model_id",
        "elevenlabs_voice_id",
        "emergency_backend",
        "language",
        "local_fallback_backend",
        "local_fallback_voice_id",
        "monthly_char_limit",
        "per_response_char_limit",
        "primary_backend",
        "schema_version",
        "selected_voice_id",
        "sentence_streaming",
        "voice_reference",
    }


def test_worker_request_timeout_stops_only_the_owned_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _backend(tmp_path)
    process = _HungWorkerProcess()
    backend._process = process  # type: ignore[assignment]
    backend._response_queue = queue.Queue()
    monkeypatch.setattr(backend, "_start", lambda: None)

    with pytest.raises(VoiceWorkerTimeout, match="VoiceWorkerTimeout"):
        backend._request({"command": "health"}, timeout_seconds=0.01)

    assert process.terminated is True
    assert process.killed is False
    assert backend._process is None
    assert '"command": "health"' in process.stdin.getvalue()


def test_chatterbox_timeout_restarts_with_bounded_piper_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _backend(tmp_path)
    calls: list[tuple[dict[str, Any], float | None]] = []

    def request(
        payload: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        calls.append((payload, timeout_seconds))
        if len(calls) == 1:
            raise VoiceWorkerTimeout("VoiceWorkerTimeout")
        return {
            "ok": True,
            "backend": "piper",
            "fallback_used": True,
            "primary_error": "VoiceWorkerTimeout",
        }

    monkeypatch.setattr(backend, "_request", request)
    response = backend._synthesis_request(
        {
            "command": "synthesize",
            "text": "Guten Abend.",
            "voice_id": "jarvis-deep-calm",
        }
    )

    assert response["backend"] == "piper"
    assert calls[0][1] == backend.synthesis_timeout_seconds
    assert calls[1][0]["backend_override"] == "piper"
    assert calls[1][0]["primary_error"] == "VoiceWorkerTimeout"
    assert calls[1][1] == backend.fallback_timeout_seconds


def test_piper_timeout_does_not_start_an_unbounded_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _backend(tmp_path)
    calls = 0

    def request(
        payload: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        nonlocal calls
        del payload, timeout_seconds
        calls += 1
        raise VoiceWorkerTimeout("VoiceWorkerTimeout")

    monkeypatch.setattr(backend, "_request", request)
    with pytest.raises(VoiceWorkerTimeout):
        backend._synthesis_request(
            {
                "command": "synthesize",
                "text": "Guten Abend.",
                "voice_id": "jarvis-piper-fast",
            }
        )
    assert calls == 1


def test_warmup_uses_its_bounded_model_loading_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _backend(tmp_path)
    calls: list[tuple[dict[str, Any], float | None]] = []

    def request(
        payload: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        calls.append((payload, timeout_seconds))
        return {
            "ok": True,
            "chatterbox_loaded": True,
            "reference_profiles_loaded": len(VOICE_REFERENCE_ASSETS),
            "piper_loaded": True,
        }

    monkeypatch.setattr(backend, "_request", request)

    assert backend.warmup() is True
    assert calls == [
        ({"command": "warmup"}, backend.warmup_timeout_seconds)
    ]


def test_auditions_must_match_the_current_voice_schema(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    voice_id = DEFAULT_VOICE_ID
    audition = backend.audition_root / f"{voice_id}.wav"
    audition.write_bytes(b"RIFF-current-test")
    metadata = audition.with_suffix(".json")
    metadata.write_text(json.dumps({"schema": "old-schema"}), encoding="utf-8")

    assert backend._audition_is_current(voice_id) is False
    with pytest.raises(FileNotFoundError, match="current voice audition"):
        backend.audition_path(voice_id)

    metadata.write_text(
        json.dumps({"schema": VOICE_CACHE_SCHEMA}), encoding="utf-8"
    )
    assert backend._audition_is_current(voice_id) is True
    assert backend.audition_path(voice_id) == audition.resolve()
