"""Tests for API key authentication middleware."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="openjarvis[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.auth_middleware import AuthMiddleware


def _make_app(api_key: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=api_key)

    @app.get("/v1/models")
    async def models():
        return {"models": []}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/webhooks/twilio")
    async def twilio_webhook():
        return {"status": "received"}

    @app.get("/metrics")
    async def metrics():
        return {"requests": 0}

    @app.get("/v1/connectors")
    async def list_connectors():
        return {"connectors": []}

    @app.get("/v1/connectors/spotify/oauth/start")
    async def oauth_start():
        return {"redirected": True}

    @app.get("/v1/connectors/spotify/oauth/callback")
    async def oauth_callback():
        return {"connected": True}

    return app


@pytest.fixture
def client():
    return TestClient(_make_app("oj_sk_test123"))


class TestAuthMiddleware:
    def test_rejects_missing_auth_header(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 401
        assert "missing" in resp.json()["detail"].lower()

    def test_rejects_wrong_key(self, client):
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    def test_accepts_valid_key(self, client):
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer oj_sk_test123"},
        )
        assert resp.status_code == 200

    def test_health_exempt(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_webhooks_exempt(self, client):
        resp = client.post("/webhooks/twilio")
        assert resp.status_code == 200

    def test_metrics_requires_auth(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 401

    def test_metrics_accepts_valid_key(self, client):
        resp = client.get("/metrics", headers={"Authorization": "Bearer oj_sk_test123"})
        assert resp.status_code == 200

    def test_no_key_configured_allows_all(self):
        client = TestClient(_make_app(""))
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        assert client.get("/metrics").status_code == 200

    def test_oauth_start_exempt(self, client):
        """GET .../oauth/start must be reachable without an Authorization
        header. It exists specifically to be opened as a plain top-level
        browser navigation (a popup window.open target) so the user can
        complete the provider's consent screen -- a browser navigation can
        never carry a custom header, so gating this route behind Bearer auth
        makes every OAuth-based connector (Google Drive/Calendar/Contacts/
        Gmail/Tasks, Spotify, Strava, ...) permanently unreachable on any
        server that has an API key configured, which is required for any
        non-loopback bind (see check_bind_safety)."""
        resp = client.get("/v1/connectors/spotify/oauth/start")
        assert resp.status_code == 200

    def test_oauth_callback_exempt(self, client):
        """GET .../oauth/callback is the provider's redirect target after
        the user approves consent -- it arrives as a plain browser
        navigation from the provider's domain and likewise can never carry
        our Authorization header."""
        resp = client.get("/v1/connectors/spotify/oauth/callback")
        assert resp.status_code == 200

    def test_other_connector_routes_still_require_auth(self, client):
        """The oauth start/callback exemption must be narrowly scoped --
        every other /v1/connectors/* route (list, connect, disconnect, sync,
        ...) still requires a valid API key."""
        resp = client.get("/v1/connectors")
        assert resp.status_code == 401
