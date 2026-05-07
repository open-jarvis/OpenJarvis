"""Tests for KokoroTTSBackend.available_voices() — Jarvis/Friday vibes free."""

from __future__ import annotations

from openjarvis.speech.kokoro_tts import KokoroTTSBackend


def test_kokoro_exposes_british_male_voices():
    """At least one British male voice (Jarvis-adjacent) must be exposed."""
    voices = KokoroTTSBackend().available_voices()
    british_male = [v for v in voices if v.startswith("bm_")]
    assert british_male, (
        f"expected at least one bm_* voice for Jarvis vibe; got {voices}"
    )


def test_kokoro_exposes_british_female_voices():
    """At least one British female voice (Friday-adjacent) must be exposed."""
    voices = KokoroTTSBackend().available_voices()
    british_female = [v for v in voices if v.startswith("bf_")]
    assert british_female, (
        f"expected at least one bf_* voice for Friday vibe; got {voices}"
    )


def test_kokoro_keeps_existing_american_voices():
    """The original 4 voices remain available so existing configs don't break."""
    voices = set(KokoroTTSBackend().available_voices())
    for legacy in ("af_heart", "af_bella", "am_adam", "am_michael"):
        assert legacy in voices, f"legacy voice {legacy} was removed"
