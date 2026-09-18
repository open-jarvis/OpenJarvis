"""Tests for speech API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

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


def test_transcribe_endpoint_offloads_backend_work(client, mock_speech_backend):
    expected = TranscriptionResult(
        text="Offloaded",
        language="en",
        confidence=0.9,
        duration_seconds=1.0,
        segments=[],
    )

    with patch(
        "openjarvis.server.api_routes.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        mock_to_thread.return_value = expected
        response = client.post(
            "/v1/speech/transcribe",
            files={"file": ("test.wav", b"fake audio data", "audio/wav")},
        )

    assert response.status_code == 200
    mock_to_thread.assert_awaited_once()
    args, kwargs = mock_to_thread.await_args
    assert args == (mock_speech_backend.transcribe, b"fake audio data")
    assert kwargs == {"format": "wav", "language": None}
    assert response.json()["text"] == "Offloaded"


def test_transcribe_endpoint_surfaces_backend_error(client, mock_speech_backend):
    mock_speech_backend.transcribe.side_effect = RuntimeError("missing cublas64_12.dll")

    response = client.post(
        "/v1/speech/transcribe",
        files={"file": ("test.wav", b"fake audio data", "audio/wav")},
    )

    assert response.status_code == 500
    assert "missing cublas64_12.dll" in response.json()["detail"]


def test_transcribe_no_file(client):
    response = client.post("/v1/speech/transcribe")
    assert response.status_code == 400 or response.status_code == 422


def test_health_endpoint(client):
    response = client.get("/v1/speech/health")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["backend"] == "mock"


def test_health_endpoint_includes_unavailable_reason(client, mock_speech_backend):
    mock_speech_backend.health.return_value = False
    mock_speech_backend.last_error.return_value = (
        "Install with: uv sync --extra desktop"
    )

    response = client.get("/v1/speech/health")

    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False
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


# ---------------------------------------------------------------------------
# Text-to-speech
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tts_backend():
    from openjarvis.speech.tts import TTSResult

    backend = MagicMock()
    backend.backend_id = "mock_tts"
    backend.health.return_value = True
    backend.synthesize.return_value = TTSResult(
        audio=b"RIFFfake-wav-bytes",
        format="wav",
        duration_seconds=1.25,
        voice_id="mock-voice",
        sample_rate=22050,
    )
    return backend


def _tts_app(backend, *, config=None):
    from fastapi import FastAPI

    from openjarvis.server.api_routes import speech_router

    app = FastAPI()
    app.include_router(speech_router)
    # Pre-resolve so the route does not go through backend discovery.
    app.state.tts_backend = backend
    app.state.tts_resolved = True
    app.state.config = config
    return TestClient(app)


def test_synthesize_returns_wav(mock_tts_backend):
    client = _tts_app(mock_tts_backend)

    response = client.post("/v1/speech/synthesize", json={"text": "Hallo Welt"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["x-sample-rate"] == "22050"
    assert response.headers["x-voice-id"] == "mock-voice"
    assert response.content == b"RIFFfake-wav-bytes"
    assert mock_tts_backend.synthesize.call_args.kwargs["output_format"] == "wav"


def test_synthesize_honours_request_overrides(mock_tts_backend):
    client = _tts_app(mock_tts_backend)

    client.post(
        "/v1/speech/synthesize",
        json={"text": "Hallo", "voice_id": "de_DE-thorsten-medium", "speed": 1.5},
    )

    kwargs = mock_tts_backend.synthesize.call_args.kwargs
    assert kwargs["voice_id"] == "de_DE-thorsten-medium"
    assert kwargs["speed"] == 1.5


def test_synthesize_rejects_empty_text(mock_tts_backend):
    client = _tts_app(mock_tts_backend)

    response = client.post("/v1/speech/synthesize", json={"text": "   "})

    assert response.status_code == 400
    mock_tts_backend.synthesize.assert_not_called()


def test_synthesize_rejects_oversized_text(mock_tts_backend):
    from openjarvis.server.api_routes import _MAX_TTS_CHARS

    client = _tts_app(mock_tts_backend)

    response = client.post(
        "/v1/speech/synthesize", json={"text": "a" * (_MAX_TTS_CHARS + 1)}
    )

    assert response.status_code == 413
    mock_tts_backend.synthesize.assert_not_called()


def test_synthesize_without_backend_returns_501():
    client = _tts_app(None)

    response = client.post("/v1/speech/synthesize", json={"text": "Hallo"})

    assert response.status_code == 501


def test_synthesize_surfaces_backend_failure(mock_tts_backend):
    mock_tts_backend.synthesize.side_effect = RuntimeError("voice model missing")
    client = _tts_app(mock_tts_backend)

    response = client.post("/v1/speech/synthesize", json={"text": "Hallo"})

    assert response.status_code == 500
    assert "voice model missing" in response.json()["detail"]


def test_synthesize_offloads_backend_work(mock_tts_backend):
    from openjarvis.speech.tts import TTSResult

    client = _tts_app(mock_tts_backend)
    expected = TTSResult(audio=b"RIFFoffloaded", format="wav", sample_rate=22050)

    with patch(
        "openjarvis.server.api_routes.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=expected,
    ) as to_thread:
        response = client.post("/v1/speech/synthesize", json={"text": "Hallo"})

    assert response.content == b"RIFFoffloaded"
    to_thread.assert_awaited_once()


def test_tts_health_reports_backend(mock_tts_backend):
    client = _tts_app(mock_tts_backend)

    data = client.get("/v1/speech/tts/health").json()

    assert data["available"] is True
    assert data["backend"] == "mock_tts"


def test_tts_health_without_backend():
    client = _tts_app(None)

    data = client.get("/v1/speech/tts/health").json()

    assert data["available"] is False
    assert "reason" in data


def test_voice_id_not_reused_across_backends(mock_tts_backend):
    """A configured voice belongs to its backend; a fallback uses its own."""
    from types import SimpleNamespace

    config = SimpleNamespace(
        speech=SimpleNamespace(
            tts_backend="kokoro", voice_id="bm_george", voice_speed=1.0
        )
    )
    client = _tts_app(mock_tts_backend, config=config)

    client.post("/v1/speech/synthesize", json={"text": "Hallo"})

    # Backend is mock_tts, not the configured kokoro, so bm_george must not leak.
    assert mock_tts_backend.synthesize.call_args.kwargs["voice_id"] != "bm_george"
