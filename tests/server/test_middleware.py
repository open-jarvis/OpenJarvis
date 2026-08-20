"""Tests for security middleware -- HTTP security headers."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.server.middleware import SECURITY_HEADERS, create_security_middleware


class TestSecurityHeaders:
    """Tests for security headers middleware."""

    def test_headers_dict(self) -> None:
        """Verify SECURITY_HEADERS has all expected keys."""
        expected_keys = {
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Strict-Transport-Security",
            "Referrer-Policy",
            "Permissions-Policy",
            "Content-Security-Policy",
        }
        assert set(SECURITY_HEADERS.keys()) == expected_keys

    def test_create_middleware_without_starlette(self) -> None:
        """When starlette is not available, returns None."""
        import importlib

        import openjarvis.server.middleware as mod

        blocked = {
            "starlette": None,
            "starlette.middleware": None,
            "starlette.middleware.base": None,
            "starlette.requests": None,
            "starlette.responses": None,
        }
        with patch.dict("sys.modules", blocked):
            importlib.reload(mod)
            result = mod.create_security_middleware()
            assert result is None
            # Reload again to restore normal state
            importlib.reload(mod)

    def test_create_middleware_with_starlette(self) -> None:
        """When starlette is available, returns a class."""
        middleware_cls = create_security_middleware()
        if middleware_cls is None:
            # starlette not installed -- skip
            import pytest

            pytest.skip("starlette not available")
        assert middleware_cls is not None
        assert callable(middleware_cls)

    def test_middleware_adds_headers(self) -> None:
        """Middleware adds all security headers to responses."""
        import pytest

        fastapi = pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        app = fastapi.FastAPI()

        middleware_cls = create_security_middleware()
        assert middleware_cls is not None
        app.add_middleware(middleware_cls)

        @app.get("/test")
        def test_endpoint() -> dict:
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200

        for header_name, header_value in SECURITY_HEADERS.items():
            assert resp.headers.get(header_name) == header_value, (
                f"Missing or wrong header: {header_name}"
            )

    def test_middleware_skips_options(self) -> None:
        """OPTIONS requests pass through without security headers."""
        import pytest

        fastapi = pytest.importorskip("fastapi")
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.testclient import TestClient

        app = fastapi.FastAPI()

        # Add CORS first, then security (reverse execution order)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        middleware_cls = create_security_middleware()
        assert middleware_cls is not None
        app.add_middleware(middleware_cls)

        @app.post("/test")
        def test_endpoint() -> dict:
            return {"ok": True}

        client = TestClient(app)
        resp = client.options(
            "/test",
            headers={
                "Origin": "https://tauri.localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers
        # Security headers should NOT be present on preflight
        assert "X-Frame-Options" not in resp.headers
