"""Tests for /api/digest endpoints."""

from __future__ import annotations

import asyncio
import threading
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


def test_generate_runs_entire_jarvis_lifecycle_on_one_worker(tmp_path, monkeypatch):
    """Construction, ask, and cleanup all stay off the event-loop thread."""
    from openjarvis.server import digest_routes

    calls: list[tuple[str, int]] = []

    class FakeJarvis:
        def __init__(self):
            calls.append(("init", threading.get_ident()))

        def __enter__(self):
            calls.append(("enter", threading.get_ident()))
            return self

        def ask(self, prompt, *, agent):
            calls.append(("ask", threading.get_ident()))
            assert prompt == "Generate my morning digest"
            assert agent == "morning_digest"
            return "digest"

        def __exit__(self, exc_type, exc, tb):
            calls.append(("exit", threading.get_ident()))

    monkeypatch.setattr("openjarvis.sdk.Jarvis", FakeJarvis)
    router = digest_routes.create_digest_router(db_path=str(tmp_path / "digest.db"))
    endpoint = next(
        route.endpoint for route in router.routes if route.path.endswith("/generate")
    )

    async def exercise():
        loop_thread = threading.get_ident()
        response = await endpoint()
        return loop_thread, response

    loop_thread, response = asyncio.run(exercise())

    assert response == {"status": "ok", "text": "digest"}
    assert [name for name, _thread in calls] == ["init", "enter", "ask", "exit"]
    assert len({thread for _name, thread in calls}) == 1
    assert calls[0][1] != loop_thread
