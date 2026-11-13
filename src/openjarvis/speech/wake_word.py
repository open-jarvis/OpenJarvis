"""Wake word detection for activating Jarvis voice mode.

Uses simple keyword matching on transcribed text. The wake word is checked
case-insensitively at the beginning of the transcription.

Note: For production use, consider dedicated wake word engines like Porcupine
or PocketSphinx. This implementation reuses the existing Whisper STT backend
by checking transcribed text after each recording segment.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Characters that may directly follow the wake word in a transcript
# (separators, punctuation) without creating a new word.
_WAKE_STRIP_CHARS = " \t.,!?;:'\"()[]{}…–—"


def _wake_words(wake_word: str) -> list[str]:
    """Normalize the wake word into its lowercase tokens.

    Supports multi-word wake words such as "open jarvis". Returns an empty list
    for blank/whitespace-only wake words.
    """
    return [token for token in wake_word.strip().lower().split() if token]


def _match_length(text: str, wake_tokens: list[str]) -> int:
    """Return the wake-word token count if ``text`` starts with it, else 0.

    Each leading token of ``text`` is compared against the corresponding wake
    token after stripping trailing separators/punctuation. Returns 0 when the
    text does not start with the wake word.
    """
    if not wake_tokens:
        return 0

    tokens = text.strip().split()
    if len(tokens) < len(wake_tokens):
        return 0

    for text_token, wake_token in zip(tokens, wake_tokens):
        if text_token.lower().strip(_WAKE_STRIP_CHARS) != wake_token:
            return 0

    return len(wake_tokens)


def check_wake_word(
    text: str,
    wake_word: str = "jarvis",
) -> bool:
    """Check if the transcribed text activates the wake word.

    The wake word must be the first token(s) of the utterance, ignoring leading
    punctuation and casing. Anything else ("Hello Jarvis", "What time is it?")
    is not a wake word.

    Args:
        text: The transcribed text from STT.
        wake_word: The wake word to detect (default: "jarvis"). May contain
            multiple words, e.g. "open jarvis".

    Returns:
        True if the wake word is detected, False otherwise.
    """
    if not text or not wake_word:
        return False

    return _match_length(text, _wake_words(wake_word)) > 0


def strip_wake_word(
    text: str,
    wake_word: str = "jarvis",
) -> str:
    """Remove a leading wake word from a transcript, returning the command.

    "Jarvis, lance le bloc-notes" -> "lance le bloc-notes"
    "Jarvis" -> ""
    "Hello Jarvis" -> "Hello Jarvis" (wake word not at the start)

    Args:
        text: The transcribed text from STT.
        wake_word: The wake word that was detected. May contain multiple words.

    Returns:
        The command text following the wake word, or the original text when
        the wake word is not present.
    """
    if not text:
        return ""

    wake_tokens = _wake_words(wake_word)
    tokens = text.strip().split()
    if not tokens:
        return ""

    matched = _match_length(text, wake_tokens)
    if matched == 0:
        # No wake word at the start of the transcript.
        return text.strip()

    remaining = [
        token for token in tokens[matched:] if token.strip(_WAKE_STRIP_CHARS)
    ]
    return " ".join(remaining).strip()


def detect_wake_word_from_backend(
    backend: Any,
    wake_word: str = "jarvis",
    language: Optional[str] = None,
) -> Optional[Callable[[bytes], Optional[bool]]]:
    """Factory function that returns a checker closure for a given STT backend.

    This is intended to be used after transcription is complete - it doesn't
    intercept the audio stream but provides a post-hoc check.

    Args:
        backend: An STT backend with a ``transcribe`` method.
        wake_word: The wake word to detect.
        language: Optional language hint for transcription.

    Returns:
        A function that takes raw audio bytes and returns True if the wake word
        is detected, or None if the backend doesn't support transcription.
    """
    if not hasattr(backend, "transcribe"):
        backend_id = getattr(backend, "backend_id", "?")
        logger.debug("Backend %s has no transcribe method", backend_id)
        return None

    def checker(audio: bytes) -> Optional[bool]:
        try:
            result = backend.transcribe(audio, format="wav", language=language)
            text = result.text.strip()
            return check_wake_word(text, wake_word)
        except Exception as exc:
            logger.debug("Wake word check failed: %s", exc)
            return None

    return checker


__all__ = [
    "check_wake_word",
    "detect_wake_word_from_backend",
    "strip_wake_word",
]
