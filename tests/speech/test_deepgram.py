"""Tests for Deepgram speech backend."""

from unittest.mock import MagicMock, patch

import pytest

from friday_ai.core.registry import SpeechRegistry
from friday_ai.speech._stubs import TranscriptionResult
from friday_ai.speech.deepgram import DeepgramSpeechBackend


@pytest.fixture(autouse=True)
def _register_deepgram():
    """Re-register after any registry clear."""
    if not SpeechRegistry.contains("deepgram"):
        SpeechRegistry.register_value("deepgram", DeepgramSpeechBackend)


def test_deepgram_registers():
    assert SpeechRegistry.contains("deepgram")


def test_deepgram_transcribe():
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_channel = MagicMock()
    mock_alternative = MagicMock()
    mock_alternative.transcript = "Hello from Deepgram"
    mock_alternative.confidence = 0.92
    mock_channel.alternatives = [mock_alternative]
    mock_channel.detected_language = "en"
    mock_result.results.channels = [mock_channel]
    mock_result.metadata.duration = 1.8
    mock_client.listen.rest.v.return_value.transcribe_file.return_value = mock_result

    with patch("friday_ai.speech.deepgram.DeepgramClient", return_value=mock_client):
        from friday_ai.speech.deepgram import DeepgramSpeechBackend

        backend = DeepgramSpeechBackend(api_key="test-key")
        result = backend.transcribe(b"fake audio", format="wav")

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello from Deepgram"


def test_deepgram_health():
    with patch("friday_ai.speech.deepgram.DeepgramClient"):
        from friday_ai.speech.deepgram import DeepgramSpeechBackend

        backend = DeepgramSpeechBackend(api_key="test-key")
        assert backend.health() is True


def test_deepgram_health_no_key():
    with patch("friday_ai.speech.deepgram.DeepgramClient"):
        from friday_ai.speech.deepgram import DeepgramSpeechBackend

        backend = DeepgramSpeechBackend.__new__(DeepgramSpeechBackend)
        backend._client = None
        backend._api_key = ""
        assert backend.health() is False
