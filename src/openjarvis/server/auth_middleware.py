"""Authentication middleware for the OpenJarvis server.

Two auth modes are supported, in this priority order:

1. **WorkOS AuthKit JWT** — when ``WORKOS_CLIENT_ID`` is set in the
   environment (or passed in), the middleware will accept access tokens
   issued by AuthKit and attach the resolved identity to
   ``request.state.user`` for downstream handlers and the trace store.
2. **Static API key** — the historical ``OPENJARVIS_API_KEY`` flow,
   kept fully backward compatible for CLI and server-to-server use.

Both modes coexist: a request with a valid AuthKit JWT *or* a matching
static key is allowed through. Webhook routes and health checks remain
exempt — they use per-channel signature verification.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_WS_AUTH_PROTOCOL = "openjarvis.auth.v1"
_WS_KEY_PROTOCOL_PREFIX = "openjarvis.key.b64url."
_JWKS_CLIENT_UNSET = object()


def _api_keys_match(presented: str, expected: str) -> bool:
    """Compare API keys as bytes so non-ASCII values do not raise ``TypeError``."""
    try:
        presented_bytes = presented.encode("utf-8")
        expected_bytes = expected.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return secrets.compare_digest(presented_bytes, expected_bytes)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates ``Authorization: Bearer <token>`` on ``/v1/*`` and ``/api/*`` routes.

    The token may be either a WorkOS AuthKit access token (JWT) or the
    static OpenJarvis API key.
    """

    def __init__(
        self,
        app,  # noqa: ANN001
        api_key: str = "",
        workos_client_id: str = "",
        workos_jwks_client: Any = _JWKS_CLIENT_UNSET,
    ) -> None:
        super().__init__(app)
        self._api_key = api_key or os.environ.get("OPENJARVIS_API_KEY", "")
        self._workos_client_id = workos_client_id or os.environ.get(
            "WORKOS_CLIENT_ID", ""
        )
        self._jwks_client = (
            _build_jwks_client(self._workos_client_id)
            if self._workos_client_id and workos_jwks_client is _JWKS_CLIENT_UNSET
            else workos_jwks_client
        )

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        # Public paths (UI, health, webhooks) bypass auth entirely.
        if not self._requires_auth(request.url.path):
            return await call_next(request)

        # If neither auth mode is configured, the server is in open
        # mode (loopback dev). check_bind_safety prevents this on
        # non-loopback hosts.
        if not self._api_key and not self._workos_client_id:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth:
            return JSONResponse(
                {"detail": "Missing Authorization header"},
                status_code=401,
            )
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                {"detail": "Invalid Authorization header"},
                status_code=401,
            )

        # Try AuthKit JWT first. If it parses but fails verification,
        # reject — we don't want to silently fall back to the static
        # key for a tampered JWT.
        if self._workos_client_id and _looks_like_jwt(token):
            if self._jwks_client is None:
                return JSONResponse(
                    {"detail": "AuthKit validation is unavailable"},
                    status_code=503,
                )
            claims = _verify_authkit_jwt(
                token,
                self._jwks_client,
                audience=self._workos_client_id,
            )
            if claims is None:
                return JSONResponse(
                    {"detail": "Invalid or expired AuthKit token"},
                    status_code=401,
                )
            request.state.user = claims
            request.state.user_id = claims.get("sub", "")
            request.state.organization_id = claims.get("org_id", "")
            return await call_next(request)

        # Fall back to the static API key path.
        if self._api_key and _api_keys_match(token, self._api_key):
            return await call_next(request)

        return JSONResponse(
            {"detail": "Invalid API key"},
            status_code=401,
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


def _looks_like_jwt(token: str) -> bool:
    """A JWT is three base64url segments separated by dots."""
    return token.count(".") == 2


def _build_jwks_client(client_id: str):
    """Construct a cached PyJWKClient for the AuthKit JWKS endpoint.

    Returns ``None`` if the client id is malformed, the optional dependency
    is unavailable, or a usable client cannot be constructed. A configured
    middleware treats that state as unavailable authentication, never open
    access.
    """
    if not client_id.startswith("client_") or not client_id[7:].isalnum():
        logger.error("Invalid WORKOS_CLIENT_ID; expected client_<alphanumeric>")
        return None
    try:
        from jwt import PyJWKClient
    except ImportError:
        logger.error(
            "WORKOS_CLIENT_ID set but `pyjwt` is not installed. "
            "Run: uv sync --extra auth-workos"
        )
        return None

    try:
        jwks_url = f"https://api.workos.com/sso/jwks/{client_id}"
        client = PyJWKClient(jwks_url, cache_keys=True)
        if not callable(getattr(client, "get_signing_key_from_jwt", None)):
            raise TypeError("JWKS client cannot resolve signing keys")
        return client
    except Exception as exc:
        logger.error("Failed to initialize AuthKit JWKS client: %s", exc)
        return None


def _verify_authkit_jwt(
    token: str,
    jwks_client,  # noqa: ANN001
    *,
    audience: str,
) -> dict[str, Any] | None:
    """Verify an AuthKit access token against the cached JWKS.

    Returns the claims dict on success, or ``None`` on any verification
    failure (signature, expiry, malformed token, network error fetching
    a key that isn't yet cached).
    """
    try:
        import jwt

        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
        )
    except Exception as exc:
        logger.debug("AuthKit JWT verification failed: %s", exc)
        return None


def generate_api_key() -> str:
    """Generate a new API key with ``oj_sk_`` prefix."""
    return f"oj_sk_{secrets.token_urlsafe(32)}"


def check_bind_safety(host: str, *, api_key: str) -> None:
    """Refuse to bind non-loopback without any auth configured.

    Raises ``SystemExit`` if *host* is not a loopback address and
    neither *api_key* nor ``WORKOS_CLIENT_ID`` is set.
    """
    import ipaddress
    import sys

    try:
        is_loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loop = host in ("localhost", "")

    has_auth = bool(api_key) or bool(os.environ.get("WORKOS_CLIENT_ID", ""))
    if not is_loop and not has_auth:
        logger.error(
            "Binding to %s requires OPENJARVIS_API_KEY or WORKOS_CLIENT_ID "
            "to be set. Run: jarvis auth generate-key",
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


def _decode_websocket_credential(credential_protocol: str) -> str:
    if not credential_protocol.startswith(_WS_KEY_PROTOCOL_PREFIX):
        return ""
    encoded = credential_protocol.removeprefix(_WS_KEY_PROTOCOL_PREFIX)
    try:
        padding = "=" * (-len(encoded) % 4)
        raw = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
        return raw.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return ""


def authenticate_websocket(
    websocket,
    expected_key: str,  # noqa: ANN001
    *,
    workos_client_id: str = "",
    workos_jwks_client: Any = None,
) -> tuple[bool, str | None]:
    """Authenticate a WebSocket and return its negotiated auth subprotocol.

    Programmatic clients can send ``Authorization: Bearer <key>``. Browser
    clients, which cannot set that header, offer ``openjarvis.auth.v1`` plus a
    marked, unpadded base64url encoding of the UTF-8 key. The encoding only
    makes the credential valid subprotocol syntax; it does not make it secret.
    """
    credential_protocol, selected_protocol = _offered_websocket_auth(websocket)

    # Match AuthMiddleware's local, keyless behavior only when neither mode is
    # configured. A broken optional WorkOS install must never open WebSockets.
    if not expected_key and not workos_client_id:
        return True, selected_protocol

    auth = websocket.headers.get("authorization", "")
    scheme, _, header_token = auth.partition(" ")
    protocol_token = _decode_websocket_credential(credential_protocol)
    presented_token = header_token if scheme.lower() == "bearer" else protocol_token

    if workos_client_id and _looks_like_jwt(presented_token):
        if workos_jwks_client is None:
            return False, selected_protocol
        claims = _verify_authkit_jwt(
            presented_token,
            workos_jwks_client,
            audience=workos_client_id,
        )
        return claims is not None, selected_protocol

    header_valid = (
        bool(expected_key)
        and scheme.lower() == "bearer"
        and (_api_keys_match(header_token, expected_key))
    )

    expected_protocol = _websocket_key_protocol(expected_key)
    protocol_valid = bool(expected_key and credential_protocol) and (
        secrets.compare_digest(credential_protocol, expected_protocol)
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
