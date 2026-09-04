"""API key authentication middleware for the OpenJarvis server."""

from __future__ import annotations

import base64
import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_WS_AUTH_PROTOCOL = "openjarvis.auth.v1"
_WS_KEY_PROTOCOL_PREFIX = "openjarvis.key.b64url."


def _api_keys_match(presented: str, expected: str) -> bool:
    """Compare API keys as bytes so non-ASCII values do not raise ``TypeError``."""
    try:
        presented_bytes = presented.encode("utf-8")
        expected_bytes = expected.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return secrets.compare_digest(presented_bytes, expected_bytes)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates ``Authorization: Bearer <key>`` on ``/v1/*`` and ``/api/*`` routes.

    Webhook routes and health checks are exempt — they use
    per-channel signature verification instead.
    """

    def __init__(self, app, api_key: str = "") -> None:  # noqa: ANN001
        super().__init__(app)
        self._api_key = api_key or os.environ.get("OPENJARVIS_API_KEY", "")

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        # Browser CORS preflights never carry Authorization, and rejecting
        # them here means they never reach CORSMiddleware to get
        # Access-Control-Allow-* headers, breaking cross-origin access
        # outright (#758). Do not exempt arbitrary OPTIONS requests: a real
        # preflight is identified by both headers required by the CORS protocol.
        if self._is_cors_preflight(request):
            return await call_next(request)
        if self._api_key and self._requires_auth(request.url.path):
            auth = request.headers.get("Authorization", "")
            if not auth:
                return JSONResponse(
                    {"detail": "Missing Authorization header"},
                    status_code=401,
                )
            scheme, _, token = auth.partition(" ")
            # Constant-time comparison to avoid leaking the key via timing.
            if scheme.lower() != "bearer" or not _api_keys_match(token, self._api_key):
                return JSONResponse(
                    {"detail": "Invalid API key"},
                    status_code=401,
                )
        return await call_next(request)

    @staticmethod
    def _is_cors_preflight(request: Request) -> bool:
        return (
            request.method == "OPTIONS"
            and bool(request.headers.get("Origin"))
            and bool(request.headers.get("Access-Control-Request-Method"))
        )

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


def _websocket_key_protocol(api_key: str) -> str:
    """Encode an API key as a browser-safe WebSocket protocol token."""
    try:
        encoded = base64.urlsafe_b64encode(api_key.encode("utf-8")).decode("ascii")
    except UnicodeEncodeError:
        return ""
    return f"{_WS_KEY_PROTOCOL_PREFIX}{encoded.rstrip('=')}"


def _offered_websocket_auth(websocket) -> tuple[str, str | None]:  # noqa: ANN001
    """Return the credential protocol and protocol to negotiate, if well formed.

    ASGI exposes the complete, flattened protocol offer in ``scope``. Reading
    it avoids ambiguity from repeated ``Sec-WebSocket-Protocol`` header fields.
    Exactly one stable protocol marker and one encoded credential are required.
    """
    offered = getattr(websocket, "scope", {}).get("subprotocols", [])
    if not isinstance(offered, (list, tuple)) or len(offered) != 2:
        return "", None
    if offered.count(_WS_AUTH_PROTOCOL) != 1:
        return "", None
    credentials = [
        protocol
        for protocol in offered
        if isinstance(protocol, str) and protocol != _WS_AUTH_PROTOCOL
    ]
    if len(credentials) != 1 or not credentials[0].startswith(_WS_KEY_PROTOCOL_PREFIX):
        return "", None
    if credentials[0] == _WS_KEY_PROTOCOL_PREFIX:
        return "", None
    return credentials[0], _WS_AUTH_PROTOCOL


def authenticate_websocket(
    websocket,  # noqa: ANN001
    expected_key: str,
) -> tuple[bool, str | None]:
    """Authenticate a WebSocket and return its negotiated auth subprotocol.

    Programmatic clients can send ``Authorization: Bearer <key>``. Browser
    clients, which cannot set that header, offer ``openjarvis.auth.v1`` plus a
    marked, unpadded base64url encoding of the UTF-8 key. The encoding only
    makes the credential valid subprotocol syntax; it does not make it secret.
    """
    credential_protocol, selected_protocol = _offered_websocket_auth(websocket)

    # Match AuthMiddleware's local, keyless behavior. If a stale client still
    # offers a well-formed auth protocol, negotiate it so the browser does not
    # fail an otherwise allowed handshake.
    if not expected_key:
        return True, selected_protocol

    auth = websocket.headers.get("authorization", "")
    scheme, _, header_token = auth.partition(" ")
    header_valid = scheme.lower() == "bearer" and _api_keys_match(
        header_token, expected_key
    )

    expected_protocol = _websocket_key_protocol(expected_key)
    protocol_valid = bool(credential_protocol and expected_protocol) and (
        _api_keys_match(credential_protocol, expected_protocol)
    )
    return header_valid or protocol_valid, selected_protocol


def websocket_authorized(websocket, expected_key: str) -> bool:  # noqa: ANN001
    """Return ``True`` if a WebSocket connection presents the expected key.

    ``AuthMiddleware`` is a ``BaseHTTPMiddleware`` and never sees WebSocket
    upgrade requests, so streaming endpoints must check the token themselves
    in the handshake before calling ``websocket.accept()``.

    When *expected_key* is empty, authentication is disabled (the loopback /
    local-only default, matching :class:`AuthMiddleware`) and all connections
    are allowed. See :func:`authenticate_websocket` for the supported
    credential transports. URL query parameters are deliberately not accepted
    because request targets commonly appear in access logs and browser history.
    """
    return authenticate_websocket(websocket, expected_key)[0]
