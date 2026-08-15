"""API key authentication middleware for the OpenJarvis server."""

from __future__ import annotations

import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates ``Authorization: Bearer <key>`` on ``/v1/*`` and ``/api/*`` routes.

    Webhook routes and health checks are exempt — they use
    per-channel signature verification instead.
    """

    def __init__(self, app, api_key: str = "") -> None:  # noqa: ANN001
        super().__init__(app)
        self._api_key = api_key or os.environ.get("OPENJARVIS_API_KEY", "")

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if self._api_key and self._requires_auth(request.url.path):
            auth = request.headers.get("Authorization", "")
            if not auth:
                return JSONResponse(
                    {"detail": "Missing Authorization header"},
                    status_code=401,
                )
            scheme, _, token = auth.partition(" ")
            # Constant-time comparison to avoid leaking the key via timing.
            if scheme.lower() != "bearer" or not secrets.compare_digest(
                token, self._api_key
            ):
                return JSONResponse(
                    {"detail": "Invalid API key"},
                    status_code=401,
                )
        return await call_next(request)

    @staticmethod
    def _requires_auth(path: str) -> bool:
        """Protect API routes and operational metrics; leave the UI/health open.

        ``/metrics`` exposes request/token counters that should not be readable
        by unauthenticated clients, so it is gated alongside ``/v1`` and
        ``/api``. ``/health`` stays open for liveness probes.
        """
        return (
            path.startswith("/v1/")
            or path.startswith("/api/")
            or path == "/metrics"
            or path.startswith("/metrics/")
        )


def generate_api_key() -> str:
    """Generate a new API key with ``oj_sk_`` prefix."""
    return f"oj_sk_{secrets.token_urlsafe(32)}"


def check_bind_safety(host: str, *, api_key: str) -> None:
    """Refuse to bind non-loopback without an API key.

    Raises ``SystemExit`` if *host* is not a loopback address and
    *api_key* is empty.
    """
    import ipaddress
    import sys

    try:
        is_loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loop = host in ("localhost", "")

    if not is_loop and not api_key:
        logger.error(
            "Binding to %s requires OPENJARVIS_API_KEY to be set. "
            "Run: jarvis auth generate-key",
            host,
        )
        sys.exit(1)


def _bearer_subprotocol_token(websocket) -> str:  # noqa: ANN001
    """Extract a token offered via ``Sec-WebSocket-Protocol: bearer, <token>``.

    Browsers can't set an ``Authorization`` header on a WebSocket handshake,
    but they can offer subprotocols, which (unlike a ``?token=`` query
    parameter) aren't part of the request line and so don't land in server
    access logs or browser history.
    """
    offered = [
        p.strip()
        for p in websocket.headers.get("sec-websocket-protocol", "").split(",")
    ]
    if len(offered) == 2 and offered[0] == "bearer" and offered[1]:
        return offered[1]
    return ""


def websocket_authorized(websocket, expected_key: str) -> bool:  # noqa: ANN001
    """Return ``True`` if a WebSocket connection presents the expected key.

    ``AuthMiddleware`` is a ``BaseHTTPMiddleware`` and never sees WebSocket
    upgrade requests, so streaming endpoints must check the token themselves
    in the handshake before calling ``websocket.accept()``.

    When *expected_key* is empty, authentication is disabled (the loopback /
    local-only default, matching :class:`AuthMiddleware`) and all connections
    are allowed. The token may be supplied via an ``Authorization: Bearer
    <key>`` header for programmatic clients, or a ``Sec-WebSocket-Protocol:
    bearer, <key>`` offer for browser clients — never via a URL query
    parameter, which would leak the key into logs.
    """
    if not expected_key:
        return True
    auth = websocket.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    token = value if scheme.lower() == "bearer" else ""
    if not token:
        token = _bearer_subprotocol_token(websocket)
    if not token:
        return False
    return secrets.compare_digest(token, expected_key)


def websocket_subprotocol(websocket) -> str | None:  # noqa: ANN001
    """Subprotocol to echo back in ``accept()`` if auth used ``Sec-WebSocket-Protocol``.

    Call after :func:`websocket_authorized` returns ``True``. Passing this
    through to ``accept(subprotocol=...)`` completes the handshake per the
    WebSocket spec, which expects the server to select one of the client's
    offered subprotocols.
    """
    return "bearer" if _bearer_subprotocol_token(websocket) else None
