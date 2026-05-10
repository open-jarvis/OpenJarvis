"""Tests for TTS text normalization."""

from __future__ import annotations

from openjarvis.speech.text_normalizer import normalize_for_tts


def test_normalize_for_tts_removes_markdown_and_links():
    text = """## Morgenbrief
- **Kalender**: [Standup](https://example.com) um 09:30
- Repo: `OpenJarvis`
"""

    result = normalize_for_tts(text)

    assert "##" not in result
    assert "**" not in result
    assert "https://" not in result
    assert "Standup" in result
    assert "9 Uhr 30" in result
    assert "OpenJarvis" in result


def test_normalize_for_tts_replaces_code_blocks():
    result = normalize_for_tts("Hier ist Code:\n```python\nprint('x')\n```")
    assert "Code ausgelassen" in result
    assert "print" not in result


def test_normalize_for_tts_shortens_long_clause_chain():
    text = (
        "Das ist ein sehr langer Satz, der mehrere Einschuebe enthaelt, "
        "damit die Sprachausgabe nicht in einem einzigen Atemzug laeuft, "
        "sondern sauberere kurze Segmente bekommt."
    )

    result = normalize_for_tts(text)

    assert ". " in result
