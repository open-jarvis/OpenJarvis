"""API key authentication middleware for the OpenJarvis server."""

from __future__ import annotations

import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths exempt from API key auth
_EXEMPT_PREFIXES = (
    "/health",
    "/webhooks/",
    "/docs",
    "/openapi.json",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates ``Authorization: Bearer <key>`` on ``/v1/*`` routes.

    Webhook routes and health checks are exempt — they use
    per-channel signature verification instead.
    """

    def __init__(self, app, api_key: str = "") -> None:  # noqa: ANN001
        super().__init__(app)
        self._api_key = api_key or os.environ.get("OPENJARVIS_API_KEY", "")

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if self._api_key and not self._is_exempt(request.url.path):
            auth = request.headers.get("Authorization", "")
            if not auth:
                return JSONResponse(
                    {"detail": "Missing Authorization header"},
                    status_code=401,
                )
            scheme, _, token = auth.partition(" ")
            if scheme.lower() != "bearer" or token != self._api_key:
                return JSONResponse(
                    {"detail": "Invalid API key"},
                    status_code=401,
                )
        return await call_next(request)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        return any(path.startswith(p) for p in _EXEMPT_PREFIXES)


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
