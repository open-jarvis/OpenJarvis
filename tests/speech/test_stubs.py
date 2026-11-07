"""Tests for speech ABC and data types."""

from friday_ai.speech._stubs import Segment, SpeechBackend, TranscriptionResult


def test_transcription_result():
    result = TranscriptionResult(
        text="Hello world",
        language="en",
        confidence=0.95,
        duration_seconds=1.5,
        segments=[],
    )
    assert result.text == "Hello world"
    assert result.language == "en"
    assert result.confidence == 0.95
    assert result.duration_seconds == 1.5
    assert result.segments == []


def test_segment():
    seg = Segment(text="Hello", start=0.0, end=0.5, confidence=0.98)
    assert seg.text == "Hello"
    assert seg.start == 0.0
    assert seg.end == 0.5


def test_speech_backend_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        SpeechBackend()
