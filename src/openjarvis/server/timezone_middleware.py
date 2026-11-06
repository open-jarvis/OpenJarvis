"""Read the caller's time zone from each request for prompt grounding."""

from __future__ import annotations

from typing import Any

from openjarvis.prompt.time_context import (
    TIMEZONE_HEADER,
    reset_request_timezone,
    set_request_timezone,
)

__all__ = ["TimezoneMiddleware"]

_HEADER = TIMEZONE_HEADER.encode("latin-1")


class TimezoneMiddleware:
    """Expose ``X-OpenJarvis-Timezone`` to prompt builders for one request.

    A plain ASGI middleware, so the value is set in the same context the
    endpoint and its streaming body run in. Unknown zones are ignored.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        value = None
        for key, raw in scope.get("headers") or ():
            if key == _HEADER:
                value = raw.decode("latin-1").strip()
                break
        token = set_request_timezone(value)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_request_timezone(token)
