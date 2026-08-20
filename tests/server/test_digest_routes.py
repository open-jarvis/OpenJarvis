"""Tests for /api/digest endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi", reason="openjarvis[server] not installed")

from openjarvis.agents.digest_store import DigestArtifact, DigestStore


@pytest.fixture()
def store(tmp_path):
    db_path = str(tmp_path / "digest.db")
    s = DigestStore(db_path=db_path)
    s.save(
        DigestArtifact(
            text="Good morning sir.",
            audio_path=tmp_path / "digest.mp3",
            sections={"messages": "3 emails"},
            sources_used=["gmail"],
            generated_at=datetime.now(timezone.utc),
            model_used="test",
            voice_used="jarvis",
        )
    )
    # Write fake audio file
    (tmp_path / "digest.mp3").write_bytes(b"fake-mp3")
    yield s
    s.close()


def _make_app(db_path: str):
    """Create a FastAPI app with the digest router using get_latest as fallback."""
    from unittest.mock import patch

    from fastapi import FastAPI

    from openjarvis.agents.digest_store import DigestStore
    from openjarvis.server.digest_routes import create_digest_router

    # Patch get_today to fall back to get_latest — avoids timezone issues in CI
    original_get_today = DigestStore.get_today

    def _get_today_or_latest(self, timezone_name="UTC"):
        result = original_get_today(self, timezone_name=timezone_name)
        if result is None:
            return self.get_latest()
        return result

    app = FastAPI()
    with patch.object(DigestStore, "get_today", _get_today_or_latest):
        app.include_router(create_digest_router(db_path=db_path))
    return app


def test_get_digest(store, tmp_path):
    from fastapi.testclient import TestClient

    app = _make_app(str(tmp_path / "digest.db"))
    client = TestClient(app)
    resp = client.get("/api/digest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Good morning sir."
    assert data["sources_used"] == ["gmail"]


def test_get_digest_audio(store, tmp_path):
    from fastapi.testclient import TestClient

    app = _make_app(str(tmp_path / "digest.db"))
    client = TestClient(app)
    resp = client.get("/api/digest/audio")
    assert resp.status_code == 200
    assert resp.content == b"fake-mp3"


def test_get_digest_404(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.digest_routes import create_digest_router

    app = FastAPI()
    app.include_router(create_digest_router(db_path=str(tmp_path / "empty.db")))

    client = TestClient(app)
    resp = client.get("/api/digest")
    assert resp.status_code == 404


def test_get_history(store, tmp_path):
    from fastapi.testclient import TestClient

    app = _make_app(str(tmp_path / "digest.db"))
    client = TestClient(app)
    resp = client.get("/api/digest/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["voice_used"] == "jarvis"
