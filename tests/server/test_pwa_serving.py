"""Tests for PWA static file serving in the SPA catch-all endpoint."""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from friday_ai.server.app import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": "hello",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


def _create_static_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary static directory with index.html and PWA files."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>SPA</body></html>")
    (static / "sw.js").write_text("// service worker")
    (static / "manifest.webmanifest").write_text('{"name":"FridayAI"}')
    (static / "pwa-192x192.png").write_bytes(b"\x89PNG placeholder")
    assets = static / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('app')")
    return static


@pytest.fixture()
def client_with_static(tmp_path, monkeypatch):
    """Create a test client with a real temporary static directory."""
    static_dir = _create_static_dir(tmp_path)
    engine = _make_engine()

    # Patch Path(__file__).parent to make static_dir resolve to our tmp dir
    original_truediv = pathlib.Path.__truediv__

    def patched_truediv(self, key):
        result = original_truediv(self, key)
        # Intercept the "static" lookup in app.py
        if key == "static" and str(self).endswith("server"):
            return static_dir
        return result

    monkeypatch.setattr(pathlib.Path, "__truediv__", patched_truediv)
    app = create_app(engine, "test-model")
    monkeypatch.undo()  # Restore immediately after app creation
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPWAServing:
    def test_sw_js_served_as_file(self, client_with_static):
        """Service worker file should be served directly, not as index.html."""
        resp = client_with_static.get("/sw.js")
        assert resp.status_code == 200
        assert "// service worker" in resp.text

    def test_manifest_served_as_file(self, client_with_static):
        """Web manifest should be served directly."""
        resp = client_with_static.get("/manifest.webmanifest")
        assert resp.status_code == 200
        assert "FridayAI" in resp.text

    def test_icon_served_as_file(self, client_with_static):
        """PWA icon should be served directly."""
        resp = client_with_static.get("/pwa-192x192.png")
        assert resp.status_code == 200
        assert b"PNG" in resp.content

    def test_api_routes_bypass_spa(self, client_with_static):
        """API routes should still work regardless of SPA catch-all."""
        resp = client_with_static.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"

    def test_path_traversal_blocked(self, client_with_static):
        """Path traversal attempts should fall back to index.html."""
        resp = client_with_static.get("/../../etc/passwd")
        assert resp.status_code == 200
        # Should get index.html, not the passwd file
        assert "SPA" in resp.text
