from __future__ import annotations

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
    PROFILE_BY_ID,
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
    assert "Guten Abend, Deaa." in AUDITION_TEXT

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
    assert profiles[0].backend == "chatterbox"
    assert any(profile.backend == "piper" for profile in profiles)
    assert all(profile.pitch_semitones <= 0 for profile in profiles)
    assert len({profile.seed for profile in profiles[:-1]}) == 4
    assert all(profile.seed > 0 for profile in profiles[:-1])


def test_config_manifest_never_contains_audio_or_reference_data(tmp_path: Path) -> None:
    path = tmp_path / "voice-config.json"
    config = load_voice_config(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == config
    assert set(raw) == {
        "cache_enabled",
        "fallback_backend",
        "language",
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


def test_warmup_uses_the_bounded_synthesis_deadline(
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
            "piper_loaded": True,
        }

    monkeypatch.setattr(backend, "_request", request)

    assert backend.warmup() is True
    assert calls == [
        ({"command": "warmup"}, backend.synthesis_timeout_seconds)
    ]
