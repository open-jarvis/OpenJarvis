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

    @app.post("/api/kiosk/respond")
    async def kiosk_respond():
        return {"ok": True}

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

    def test_loopback_kiosk_request_is_exempt(self):
        client = TestClient(
            _make_app("oj_sk_test123"),
            client=("127.0.0.1", 50000),
        )
        assert client.post("/api/kiosk/respond").status_code == 200

    def test_remote_kiosk_request_requires_auth(self):
        client = TestClient(
            _make_app("oj_sk_test123"),
            client=("203.0.113.10", 50000),
        )
        assert client.post("/api/kiosk/respond").status_code == 401

    def test_loopback_non_kiosk_api_still_requires_auth(self):
        client = TestClient(
            _make_app("oj_sk_test123"),
            client=("127.0.0.1", 50000),
        )
        assert client.get("/v1/models").status_code == 401

    def test_no_key_configured_allows_all(self):
        client = TestClient(_make_app(""))
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        assert client.get("/metrics").status_code == 200
