"""Tests for /api/digest endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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
            generated_at=datetime.now(),
            model_used="test",
            voice_used="jarvis",
        )
    )
    # Write fake audio file
    (tmp_path / "digest.mp3").write_bytes(b"fake-mp3")
    yield s
    s.close()


def test_get_digest(store, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.digest_routes import create_digest_router

    app = FastAPI()
    app.include_router(
        create_digest_router(db_path=str(tmp_path / "digest.db"))
    )

    client = TestClient(app)
    resp = client.get("/api/digest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Good morning sir."
    assert data["sources_used"] == ["gmail"]


def test_get_digest_audio(store, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.digest_routes import create_digest_router

    app = FastAPI()
    app.include_router(
        create_digest_router(db_path=str(tmp_path / "digest.db"))
    )

    client = TestClient(app)
    resp = client.get("/api/digest/audio")
    assert resp.status_code == 200
    assert resp.content == b"fake-mp3"


def test_get_digest_404(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.digest_routes import create_digest_router

    app = FastAPI()
    app.include_router(
        create_digest_router(db_path=str(tmp_path / "empty.db"))
    )

    client = TestClient(app)
    resp = client.get("/api/digest")
    assert resp.status_code == 404


def test_get_history(store, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.digest_routes import create_digest_router

    app = FastAPI()
    app.include_router(
        create_digest_router(db_path=str(tmp_path / "digest.db"))
    )

    client = TestClient(app)
    resp = client.get("/api/digest/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["voice_used"] == "jarvis"
