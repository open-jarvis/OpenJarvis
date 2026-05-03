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

import logging
import os
import secrets
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


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
    ) -> None:
        super().__init__(app)
        self._api_key = api_key or os.environ.get("OPENJARVIS_API_KEY", "")
        self._workos_client_id = workos_client_id or os.environ.get(
            "WORKOS_CLIENT_ID", ""
        )
        self._jwks_client = None
        if self._workos_client_id:
            self._jwks_client = _build_jwks_client(self._workos_client_id)

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        # Public paths (UI, health, webhooks) bypass auth entirely.
        if not self._requires_auth(request.url.path):
            return await call_next(request)

        # If neither auth mode is configured, the server is in open
        # mode (loopback dev). check_bind_safety prevents this on
        # non-loopback hosts.
        if not self._api_key and not self._jwks_client:
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
        if self._jwks_client and _looks_like_jwt(token):
            claims = _verify_authkit_jwt(token, self._jwks_client)
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
        if self._api_key and secrets.compare_digest(token, self._api_key):
            return await call_next(request)

        return JSONResponse(
            {"detail": "Invalid API key"},
            status_code=401,
        )

    @staticmethod
    def _requires_auth(path: str) -> bool:
        """Only protect API routes, not the frontend UI or static assets."""
        return path.startswith("/v1/") or path.startswith("/api/")


def _looks_like_jwt(token: str) -> bool:
    """A JWT is three base64url segments separated by dots."""
    return token.count(".") == 2


def _build_jwks_client(client_id: str):
    """Construct a cached PyJWKClient for the AuthKit JWKS endpoint.

    Returns ``None`` and logs at debug level if the optional
    ``auth-workos`` extra isn't installed; the middleware then behaves
    as if AuthKit weren't configured.
    """
    try:
        from jwt import PyJWKClient
        from workos import WorkOSClient
    except ImportError:
        logger.debug(
            "WORKOS_CLIENT_ID set but `workos`/`pyjwt` not installed. "
            "Run: uv sync --extra auth-workos"
        )
        return None

    api_key = os.environ.get("WORKOS_API_KEY", "")
    workos_client = WorkOSClient(api_key=api_key, client_id=client_id)
    jwks_url = workos_client.user_management.get_jwks_url(client_id)
    return PyJWKClient(jwks_url, cache_keys=True)


def _verify_authkit_jwt(token: str, jwks_client) -> dict[str, Any] | None:  # noqa: ANN001
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
            options={"verify_aud": False},
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
