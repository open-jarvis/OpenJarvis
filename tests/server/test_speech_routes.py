"""Tests for speech API endpoints."""

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.speech._stubs import TranscriptionResult  # noqa: E402
from openjarvis.speech.tts import TTSResult  # noqa: E402


@pytest.fixture
def mock_speech_backend():
    backend = MagicMock()
    backend.backend_id = "mock"
    backend.health.return_value = True
    backend.transcribe.return_value = TranscriptionResult(
        text="Hello world",
        language="en",
        confidence=0.95,
        duration_seconds=1.5,
        segments=[],
    )
    return backend


@pytest.fixture
def app_with_speech(mock_speech_backend):
    from fastapi import FastAPI

    from openjarvis.server.api_routes import speech_router

    app = FastAPI()
    app.state.speech_backend = mock_speech_backend
    app.include_router(speech_router)
    return app


@pytest.fixture
def client(app_with_speech):
    return TestClient(app_with_speech)


def test_transcribe_endpoint(client, mock_speech_backend):
    response = client.post(
        "/v1/speech/transcribe",
        files={"file": ("test.wav", b"fake audio data", "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "Hello world"
    assert data["language"] == "en"
    assert data["confidence"] == 0.95
    assert data["duration_seconds"] == 1.5


def test_transcribe_endpoint_redacts_backend_error(client, mock_speech_backend):
    mock_speech_backend.transcribe.side_effect = RuntimeError("missing cublas64_12.dll")

    response = client.post(
        "/v1/speech/transcribe",
        files={"file": ("test.wav", b"fake audio data", "audio/wav")},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Speech transcription failed (RuntimeError)"
    assert "cublas" not in response.text


def test_transcribe_rejects_non_audio_and_oversized_upload(client):
    invalid = client.post(
        "/v1/speech/transcribe",
        files={"file": ("test.txt", b"not audio", "text/plain")},
    )
    assert invalid.status_code == 415

    oversized = client.post(
        "/v1/speech/transcribe",
        files={"file": ("test.wav", b"x" * (10 * 1024 * 1024 + 1), "audio/wav")},
    )
    assert oversized.status_code == 413


def test_transcribe_no_file(client):
    response = client.post("/v1/speech/transcribe")
    assert response.status_code == 400 or response.status_code == 422


def test_health_endpoint(client):
    response = client.get("/v1/speech/health")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["backend"] == "mock"
    assert data["stt_available"] is True
    assert data["tts_available"] is False
    assert data["language"] == "de"
    assert data["microphone_permission"] == "client"


def test_health_endpoint_includes_unavailable_reason(client, mock_speech_backend):
    mock_speech_backend.health.return_value = False
    mock_speech_backend.last_error.return_value = (
        "Install with: uv sync --extra desktop"
    )

    response = client.get("/v1/speech/health")

    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False
    assert data["stt_provider"] == "mock"
    assert data["reason"] == "Install with: uv sync --extra desktop"


def test_health_no_backend():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.api_routes import speech_router

    app = FastAPI()
    app.state.speech_backend = None
    app.include_router(speech_router)
    client = TestClient(app)

    response = client.get("/v1/speech/health")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False
    assert data["stt_provider"] == "disabled"
    assert data["tts_provider"] == "disabled"


def test_local_voice_synthesis_selection_and_audition_routes(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.api_routes import speech_router

    backend = MagicMock()
    backend.backend_id = "chatterbox+piper"
    backend.health.return_value = True
    backend.voice_status.return_value = {
        "selected_voice_id": "jarvis-deep-calm",
        "profiles": [],
    }
    backend.synthesize.return_value = TTSResult(
        audio=b"RIFF-test",
        format="wav",
        voice_id="jarvis-deep-calm",
        metadata={
            "backend": "piper",
            "cache_hit": True,
            "fallback_used": True,
            "synthesis_ms": 12.5,
        },
    )
    audition = tmp_path / "jarvis-deep-calm.wav"
    audition.write_bytes(b"RIFF-audition")
    backend.audition_path.return_value = audition
    backend.generate_auditions.return_value = [{"voice_id": "jarvis-deep-calm"}]

    app = FastAPI()
    app.state.speech_backend = None
    app.state.tts_backend = backend
    app.include_router(speech_router)
    client = TestClient(app)

    speech = client.post("/v1/speech/synthesize", json={"text": "Guten Abend."})
    assert speech.status_code == 200
    assert speech.content == b"RIFF-test"
    assert speech.headers["x-openjarvis-tts-backend"] == "piper"
    assert speech.headers["x-openjarvis-cache"] == "hit"
    assert speech.headers["x-openjarvis-fallback"] == "true"

    assert client.get("/v1/speech/voices").status_code == 200
    selected = client.put(
        "/v1/speech/voices/selected", json={"voice_id": "jarvis-deep-calm"}
    )
    assert selected.json()["status"] == "saved"
    generated = client.post("/v1/speech/auditions/generate")
    assert generated.json()["status"] == "ready"
    sample = client.get("/v1/speech/auditions/jarvis-deep-calm.wav")
    assert sample.status_code == 200
    assert sample.content == b"RIFF-audition"


def test_local_voice_api_rejects_invalid_text_and_redacts_worker_errors():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.api_routes import speech_router

    backend = MagicMock()
    backend.voice_status.return_value = {}
    backend.synthesize.side_effect = RuntimeError("C:\\private\\model-token")
    app = FastAPI()
    app.state.tts_backend = backend
    app.include_router(speech_router)
    client = TestClient(app)

    assert client.post("/v1/speech/synthesize", json={"text": ""}).status_code == 422
    failed = client.post("/v1/speech/synthesize", json={"text": "Hallo"})
    assert failed.status_code == 503
    assert "private" not in failed.text
    assert "token" not in failed.text
