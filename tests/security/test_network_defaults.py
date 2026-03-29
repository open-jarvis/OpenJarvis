"""Tests for secure network defaults (Section 1 of security hardening)."""

from __future__ import annotations

import ipaddress

import pytest


class TestServerConfigDefaults:
    """ServerConfig should bind to loopback by default."""

    def test_default_host_is_loopback(self) -> None:
        from openjarvis.core.config import ServerConfig

        cfg = ServerConfig()
        assert cfg.host == "127.0.0.1"

    def test_default_port_unchanged(self) -> None:
        from openjarvis.core.config import ServerConfig

        cfg = ServerConfig()
        assert cfg.port == 8000

    def test_cors_origins_default(self) -> None:
        from openjarvis.core.config import ServerConfig

        cfg = ServerConfig()
        assert isinstance(cfg.cors_origins, list)
        assert "http://localhost:3000" in cfg.cors_origins
        assert "http://localhost:5173" in cfg.cors_origins
        assert "tauri://localhost" in cfg.cors_origins
        assert "*" not in cfg.cors_origins


class TestSecurityConfigDefaults:
    """SecurityConfig should default to redact mode with rate limiting."""

    def test_default_mode_is_redact(self) -> None:
        from openjarvis.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.mode == "redact"

    def test_rate_limiting_enabled_by_default(self) -> None:
        from openjarvis.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.rate_limit_enabled is True

    def test_bypass_defaults_conservative(self) -> None:
        from openjarvis.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.local_engine_bypass is False
        assert cfg.local_tool_bypass is False

    def test_profile_default_empty(self) -> None:
        from openjarvis.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.profile == ""


def _is_loopback(host: str) -> bool:
    """Check if a host string is a loopback address."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "")


class TestNonLoopbackAuthEnforcement:
    """Server must require API key when binding non-loopback."""

    def test_loopback_allows_no_key(self) -> None:
        assert _is_loopback("127.0.0.1")

    def test_wildcard_is_not_loopback(self) -> None:
        assert not _is_loopback("0.0.0.0")

    def test_non_loopback_requires_key(self) -> None:
        starlette = pytest.importorskip("starlette")  # noqa: F841
        from openjarvis.server.auth_middleware import check_bind_safety

        try:
            check_bind_safety("0.0.0.0", api_key="")
            assert False, "Should have raised"
        except SystemExit:
            pass

    def test_non_loopback_with_key_ok(self) -> None:
        starlette = pytest.importorskip("starlette")  # noqa: F841
        from openjarvis.server.auth_middleware import check_bind_safety

        check_bind_safety("0.0.0.0", api_key="oj_sk_test123")


class TestCORSConfiguration:
    """CORS should use configured origins, not wildcard."""

    def test_create_app_uses_configured_origins(self) -> None:
        pytest.importorskip("fastapi")
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from openjarvis.server.app import create_app

        mock_engine = MagicMock()
        mock_engine.health.return_value = True
        mock_engine.list_models.return_value = ["test-model"]

        app = create_app(
            mock_engine,
            "test-model",
            cors_origins=["http://localhost:3000"],
        )
        client = TestClient(app)

        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
        )

        resp2 = client.options(
            "/health",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp2.headers.get("access-control-allow-origin") != "http://evil.com"
