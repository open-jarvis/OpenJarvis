"""Tests for STT hallucination filtering."""

from openjarvis.speech.speech_filter import (
    is_likely_hallucination,
    sanitize_transcription,
)


def test_filters_you_hallucination():
    assert sanitize_transcription("you") == ""
    assert is_likely_hallucination("you") is True


def test_keeps_real_english():
    text = "Schedule a meeting for tomorrow at three pm"
    assert sanitize_transcription(text) == text


def test_filters_thank_you():
    assert sanitize_transcription("Thank you.") == ""
