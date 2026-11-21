"""Tests for the Windows SAPI TTS backend (local, no cloud, no torch)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows SAPI only")


@pytest.fixture(scope="module")
def backend():
    from openjarvis.speech.windows_tts import WindowsTTSBackend

    instance = WindowsTTSBackend()
    if not instance.health():
        pytest.skip("Windows System.Speech is not available")
    return instance


def test_backend_registers() -> None:
    from openjarvis.core.registry import TTSRegistry
    from openjarvis.speech.windows_tts import WindowsTTSBackend

    if not TTSRegistry.contains("windows"):
        TTSRegistry.register_value("windows", WindowsTTSBackend)
    assert TTSRegistry.contains("windows")


def test_health_is_true(backend) -> None:
    assert backend.health() is True


def test_reports_installed_voices(backend) -> None:
    assert backend.available_voices()


def test_synthesize_returns_wav(backend) -> None:
    result = backend.synthesize("Bonjour, test de synthèse vocale.")
    assert result.audio[:4] == b"RIFF"
    assert result.format == "wav"
    assert len(result.audio) > 1000


def test_synthesize_rejects_empty_text(backend) -> None:
    with pytest.raises(ValueError):
        backend.synthesize("   ")


def test_discovery_falls_back_to_windows_when_kokoro_missing() -> None:
    from openjarvis.speech._tts_discovery import get_tts_backend

    selected = get_tts_backend("kokoro")
    if selected is None:
        pytest.skip("no TTS backend available")
    assert selected.backend_id in {"windows", "kokoro"}
