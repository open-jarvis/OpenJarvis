"""Tests for speech API endpoints."""

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.speech._stubs import TranscriptionResult  # noqa: E402


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


def test_transcribe_no_file(client):
    response = client.post("/v1/speech/transcribe")
    assert response.status_code == 400 or response.status_code == 422


def test_health_endpoint(client):
    response = client.get("/v1/speech/health")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["backend"] == "mock"


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


# ---------------------------------------------------------------------------
# Synthesize (TTS) endpoint
# ---------------------------------------------------------------------------


def _tts_client(backend, config=None):
    from fastapi import FastAPI

    from openjarvis.server.api_routes import speech_router

    app = FastAPI()
    app.state.tts_backend = backend
    if config is not None:
        app.state.config = config
    app.include_router(speech_router)
    return TestClient(app)


@pytest.fixture
def mock_tts_backend():
    from types import SimpleNamespace

    backend = MagicMock()
    backend.backend_id = "mocktts"
    backend.health.return_value = True
    backend.synthesize_stream.return_value = iter([b"aud", b"io", b"123"])
    backend.synthesize.return_value = SimpleNamespace(audio=b"buffered-clip")
    return backend


def test_synthesize_streams_chunks(mock_tts_backend):
    client = _tts_client(mock_tts_backend)
    response = client.post("/v1/speech/synthesize", json={"text": "hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == b"audio123"
    mock_tts_backend.synthesize_stream.assert_called_once()
    mock_tts_backend.synthesize.assert_not_called()


def test_synthesize_buffered_when_streaming_disabled(mock_tts_backend):
    from types import SimpleNamespace

    config = SimpleNamespace(
        speech=SimpleNamespace(
            tts_voice_id="onyx", tts_speed=1.0, tts_stream=False
        )
    )
    client = _tts_client(mock_tts_backend, config=config)
    response = client.post("/v1/speech/synthesize", json={"text": "hello"})
    assert response.status_code == 200
    assert response.content == b"buffered-clip"
    mock_tts_backend.synthesize.assert_called_once()
    mock_tts_backend.synthesize_stream.assert_not_called()


def test_synthesize_missing_text(mock_tts_backend):
    client = _tts_client(mock_tts_backend)
    response = client.post("/v1/speech/synthesize", json={"text": "   "})
    assert response.status_code == 400


def test_synthesize_no_backend():
    client = _tts_client(None)
    response = client.post("/v1/speech/synthesize", json={"text": "hello"})
    assert response.status_code == 501
