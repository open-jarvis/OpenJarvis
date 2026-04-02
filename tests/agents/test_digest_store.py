"""Tests for DigestStore and DigestArtifact."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from openjarvis.agents.digest_store import DigestArtifact, DigestStore


def test_store_and_retrieve(tmp_path):
    store = DigestStore(db_path=str(tmp_path / "digest.db"))

    artifact = DigestArtifact(
        text="Good morning sir.",
        audio_path=Path("/tmp/digest.mp3"),
        sections={"messages": "You have 3 emails.", "calendar": "2 meetings today."},
        sources_used=["gmail", "gcalendar"],
        generated_at=datetime(2026, 4, 1, 6, 0, 0),
        model_used="claude-sonnet-4-6",
        voice_used="jarvis-v1",
    )

    store.save(artifact)
    retrieved = store.get_latest()

    assert retrieved is not None
    assert retrieved.text == "Good morning sir."
    assert retrieved.sections["messages"] == "You have 3 emails."
    assert retrieved.sources_used == ["gmail", "gcalendar"]
    assert retrieved.voice_used == "jarvis-v1"

    store.close()


def test_get_today(tmp_path):
    store = DigestStore(db_path=str(tmp_path / "digest.db"))
    artifact = DigestArtifact(
        text="Today's digest",
        audio_path=Path("/tmp/today.mp3"),
        sections={"messages": "Nothing urgent."},
        sources_used=["gmail"],
        generated_at=datetime.now(),
        model_used="test-model",
        voice_used="jarvis",
    )
    store.save(artifact)
    today = store.get_today()
    assert today is not None
    assert today.text == "Today's digest"
    store.close()


def test_get_today_returns_none_when_empty(tmp_path):
    store = DigestStore(db_path=str(tmp_path / "digest.db"))
    assert store.get_today() is None
    store.close()


def test_history(tmp_path):
    store = DigestStore(db_path=str(tmp_path / "digest.db"))
    for i in range(3):
        store.save(
            DigestArtifact(
                text=f"Digest {i}",
                audio_path=Path(f"/tmp/d{i}.mp3"),
                sections={},
                sources_used=[],
                generated_at=datetime(2026, 4, 1 + i, 6, 0, 0),
                model_used="test",
                voice_used="jarvis",
            )
        )
    history = store.history(limit=2)
    assert len(history) == 2
    assert history[0].text == "Digest 2"  # Most recent first
    store.close()
