"""Tests for wake word detection and wake-word stripping."""

from __future__ import annotations

import pytest

from openjarvis.speech.wake_word import (
    check_wake_word,
    detect_wake_word_from_backend,
    strip_wake_word,
)


class _FakeBackend:
    """Minimal STT backend double exposing ``transcribe``."""

    backend_id = "fake"

    def __init__(self, text: str) -> None:
        self._text = text

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: str | None = None,
    ) -> object:
        return type("FakeResult", (), {"text": self._text})()


class TestCheckWakeWord:
    @pytest.mark.parametrize(
        ("text", "wake_word", "expected"),
        [
            ("Jarvis, what's the time?", "jarvis", True),
            ("Jarvis, lance le bloc-notes", "jarvis", True),
            ("jarvis open the door", "jarvis", True),
            ("Jarvis", "jarvis", True),
            ("Hello Jarvis", "jarvis", False),
            ("What time is it?", "jarvis", False),
            ("", "jarvis", False),
            ("J'arrive", "jarvis", False),
            ("Jarvisly is not a wake word", "jarvis", False),
        ],
    )
    def test_check_wake_word(self, text: str, wake_word: str, expected: bool) -> None:
        assert check_wake_word(text, wake_word) is expected


class TestStripWakeWord:
    def test_strip_removes_leading_wake_word(self) -> None:
        assert (
            strip_wake_word("Jarvis, lance le bloc-notes", "jarvis")
            == "lance le bloc-notes"
        )

    def test_strip_removes_wake_word_alone(self) -> None:
        assert strip_wake_word("Jarvis", "jarvis") == ""

    def test_strip_leaves_text_without_wake_word(self) -> None:
        assert strip_wake_word("Hello Jarvis", "jarvis") == "Hello Jarvis"

    def test_strip_empty_text(self) -> None:
        assert strip_wake_word("", "jarvis") == ""

    def test_multiword_wake_word_check(self) -> None:
        assert check_wake_word("Open jarvis, lance le bloc-notes", "open jarvis")
        assert not check_wake_word("Open the door", "open jarvis")

    def test_multiword_wake_word_strip(self) -> None:
        assert (
            strip_wake_word("Open jarvis, lance le bloc-notes", "open jarvis")
            == "lance le bloc-notes"
        )
        assert strip_wake_word("Open the door", "open jarvis") == "Open the door"


class TestDetectWakeWordFromBackend:
    def test_backend_without_transcribe_returns_none(self) -> None:
        assert detect_wake_word_from_backend(object()) is None

    def test_checker_uses_transcription_result(self) -> None:
        checker = detect_wake_word_from_backend(_FakeBackend("Jarvis, quelle heure ?"))
        assert checker is not None
        assert checker(b"wav") is True
