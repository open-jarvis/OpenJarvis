"""Tests for OpenAI Whisper API speech backend."""

from unittest.mock import MagicMock, patch

import pytest

from friday_ai.core.registry import SpeechRegistry
from friday_ai.speech._stubs import TranscriptionResult
from friday_ai.speech.openai_whisper import OpenAIWhisperBackend


@pytest.fixture(autouse=True)
def _register_openai_whisper():
    """Re-register after any registry clear."""
    if not SpeechRegistry.contains("openai"):
        SpeechRegistry.register_value("openai", OpenAIWhisperBackend)


def test_openai_whisper_registers():
    assert SpeechRegistry.contains("openai")


def test_openai_whisper_transcribe():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello from OpenAI"
    mock_response.language = "en"
    mock_response.duration = 2.0
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch("friday_ai.speech.openai_whisper.OpenAI", return_value=mock_client):
        from friday_ai.speech.openai_whisper import OpenAIWhisperBackend

        backend = OpenAIWhisperBackend(api_key="test-key")
        result = backend.transcribe(b"fake audio", format="wav")

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello from OpenAI"
        assert result.language == "en"


def test_openai_whisper_health():
    with patch("friday_ai.speech.openai_whisper.OpenAI"):
        from friday_ai.speech.openai_whisper import OpenAIWhisperBackend

        backend = OpenAIWhisperBackend(api_key="test-key")
        assert backend.health() is True


def test_openai_whisper_health_no_key():
    with patch("friday_ai.speech.openai_whisper.OpenAI"):
        from friday_ai.speech.openai_whisper import OpenAIWhisperBackend

        backend = OpenAIWhisperBackend.__new__(OpenAIWhisperBackend)
        backend._client = None
        backend._api_key = ""
        assert backend.health() is False
