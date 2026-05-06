"""HTTP Basic Auth middleware — env-gated, defense-in-depth network gate.

Activates when both `OPENJARVIS_BASIC_AUTH_USER` and
`OPENJARVIS_BASIC_AUTH_PASSWORD` are set. Otherwise it's a pass-through.

Skipped paths (always public):
  - /health      (Railway probe; locking it out causes restart loops)
  - /            (frontend SPA — auth happens via the browser prompt
                  triggered by the first XHR/SSE call)

The browser caches credentials per-origin once the user enters them, so
follow-up XHR + EventSource (SSE) requests carry them automatically. No
frontend changes needed.
"""

from __future__ import annotations

import base64
import hmac
import logging
import os
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# Paths that must always succeed without auth — Railway health probes,
# the public SPA shell, and static assets the SPA loads to display the
# auth prompt itself.
_PUBLIC_PATH_PREFIXES = (
    "/health",
    "/assets/",
    "/static/",
    "/favicon",
    "/manifest",
)


def _expected_creds() -> tuple[str, str] | None:
    user = os.environ.get("OPENJARVIS_BASIC_AUTH_USER")
    password = os.environ.get("OPENJARVIS_BASIC_AUTH_PASSWORD")
    if not user or not password:
        return None
    return (user, password)


def _is_public(path: str) -> bool:
    if path == "/":
        return True
    return any(path.startswith(p) for p in _PUBLIC_PATH_PREFIXES)


def _check(header: str, expected_user: str, expected_password: str) -> bool:
    if not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8", errors="replace")
        user, _, password = decoded.partition(":")
    except Exception:
        return False
    # Constant-time compare to avoid trivial timing leaks
    return (
        hmac.compare_digest(user, expected_user)
        and hmac.compare_digest(password, expected_password)
    )


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        creds = _expected_creds()
        if creds is None:
            return await call_next(request)

        if _is_public(request.url.path):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not _check(header, creds[0], creds[1]):
            return Response(
                status_code=401,
                content="Authentication required.",
                headers={"WWW-Authenticate": 'Basic realm="OpenJarvis"'},
            )

        return await call_next(request)


def is_enabled() -> bool:
    return _expected_creds() is not None


__all__ = ["BasicAuthMiddleware", "is_enabled"]
