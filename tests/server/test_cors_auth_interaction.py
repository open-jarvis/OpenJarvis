"""Regression tests for #758: CORS preflight broken when an API key is set.

AuthMiddleware is added after CORSMiddleware in create_app(), and Starlette
runs middleware in reverse registration order, so AuthMiddleware sits
outermost. A browser preflight (OPTIONS, no Authorization header) used to be
rejected with a bare 401 by AuthMiddleware before ever reaching
CORSMiddleware, so the response carried no Access-Control-Allow-Origin
header and the browser treated the whole cross-origin request as blocked.
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
