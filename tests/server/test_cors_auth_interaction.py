"""Regression tests for #758: CORS preflight broken when an API key is set.

CORSMiddleware is the outermost layer so it can both answer real preflights
and decorate AuthMiddleware's 401 responses. Without that ordering, browsers
surface an opaque CORS network failure instead of the actionable auth error.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402


def _make_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    return engine


def _test_config():
    from openjarvis.core.config import JarvisConfig

    cfg = JarvisConfig()
    cfg.analytics.enabled = False
    cfg.traces.enabled = False
    return cfg


class TestCorsPreflightWithApiKey:
    def test_environment_origins_used_when_factory_argument_is_omitted(
        self, monkeypatch
    ):
        monkeypatch.setenv("OPENJARVIS_CORS_ORIGINS", "https://frontend.example")
        app = create_app(
            _make_engine(),
            "test-model",
            config=_test_config(),
            api_key="oj_sk_test123",
        )
        client = TestClient(app)

        resp = client.options(
            "/v1/models",
            headers={
                "Origin": "https://frontend.example",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == (
            "https://frontend.example"
        )

    def test_explicit_factory_origins_override_environment(self, monkeypatch):
        monkeypatch.setenv("OPENJARVIS_CORS_ORIGINS", "https://env.example")
        app = create_app(
            _make_engine(),
            "test-model",
            config=_test_config(),
            api_key="oj_sk_test123",
            cors_origins=["https://explicit.example"],
        )
        client = TestClient(app)

        explicit = client.options(
            "/v1/models",
            headers={
                "Origin": "https://explicit.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        env = client.options(
            "/v1/models",
            headers={
                "Origin": "https://env.example",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert explicit.status_code == 200
        assert env.status_code == 400

    def test_wildcard_origin_is_removed(self, monkeypatch):
        monkeypatch.setenv("OPENJARVIS_CORS_ORIGINS", "*")
        app = create_app(
            _make_engine(),
            "test-model",
            config=_test_config(),
            api_key="oj_sk_test123",
        )
        client = TestClient(app)

        resp = client.options(
            "/v1/models",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert resp.status_code == 400
        assert "access-control-allow-origin" not in resp.headers

    def test_preflight_gets_cors_headers_not_401(self):
        app = create_app(
            _make_engine(),
            "test-model",
            config=_test_config(),
            api_key="oj_sk_test123",
            cors_origins=["https://example.com"],
        )
        client = TestClient(app)

        resp = client.options(
            "/v1/models",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert resp.status_code != 401
        assert resp.headers.get("access-control-allow-origin") == "https://example.com"

    def test_actual_request_still_requires_auth(self):
        """The fix must not accidentally exempt real GET/POST requests."""
        app = create_app(
            _make_engine(),
            "test-model",
            config=_test_config(),
            api_key="oj_sk_test123",
            cors_origins=["https://example.com"],
        )
        client = TestClient(app)

        resp = client.get("/v1/models", headers={"Origin": "https://example.com"})
        assert resp.status_code == 401
        assert resp.headers.get("access-control-allow-origin") == "https://example.com"

    def test_plain_options_is_not_an_auth_bypass(self):
        app = create_app(
            _make_engine(),
            "test-model",
            config=_test_config(),
            api_key="oj_sk_test123",
            cors_origins=["https://example.com"],
        )
        client = TestClient(app)

        resp = client.options("/v1/models")
        assert resp.status_code == 401

    def test_disallowed_origin_gets_no_cors_header(self):
        app = create_app(
            _make_engine(),
            "test-model",
            config=_test_config(),
            api_key="oj_sk_test123",
            cors_origins=["https://example.com"],
        )
        client = TestClient(app)

        resp = client.get("/v1/models", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 401
        assert "access-control-allow-origin" not in resp.headers
