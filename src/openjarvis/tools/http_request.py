"""HTTP request tool — make HTTP requests with SSRF protection."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.security.ssrf import check_ssrf
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

# Maximum response body size: 1 MB
_MAX_RESPONSE_BYTES = 1_048_576

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"})


@ToolRegistry.register("http_request")
class HttpRequestTool(BaseTool):
    """Make HTTP requests to external APIs with SSRF protection."""

    tool_id = "http_request"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="http_request",
            description=(
                "Make an HTTP request to a URL."
                " Supports GET, POST, PUT, DELETE, PATCH,"
                " and HEAD methods. Includes SSRF protection"
                " against private IPs and cloud metadata."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to send the request to.",
                    },
                    "method": {
                        "type": "string",
                        "description": (
                            "HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD)."
                            " Defaults to GET."
                        ),
                    },
                    "headers": {
                        "type": "object",
                        "description": "Optional HTTP headers as key-value pairs.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional request body (for POST, PUT, PATCH).",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Request timeout in seconds. Defaults to 30.",
                    },
                },
                "required": ["url"],
            },
            category="network",
            required_capabilities=["network:fetch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        url = params.get("url", "")
        if not url:
            return ToolResult(
                tool_name="http_request",
                content="No URL provided.",
                success=False,
            )

        method = params.get("method", "GET").upper()
        if method not in _ALLOWED_METHODS:
            return ToolResult(
                tool_name="http_request",
                content=(
                    f"Unsupported HTTP method: {method}."
                    f" Allowed: {', '.join(sorted(_ALLOWED_METHODS))}."
                ),
                success=False,
            )

        # SSRF protection check
        ssrf_error = check_ssrf(url)
        if ssrf_error:
            return ToolResult(
                tool_name="http_request",
                content=f"SSRF protection blocked request: {ssrf_error}",
                success=False,
            )

        headers = params.get("headers") or {}
        body = params.get("body")
        timeout = params.get("timeout", 30)

        _rust = None
        try:
            from openjarvis._rust_bridge import get_rust_module

            _rust = get_rust_module()
        except ImportError:
            pass
        if _rust is not None and not headers:
            try:
                content = _rust.HttpRequestTool().execute(url, method, body)
                return ToolResult(
                    tool_name="http_request",
                    content=(
                        content[:_MAX_RESPONSE_BYTES]
                        if len(content) > _MAX_RESPONSE_BYTES
                        else content
                    ),
                    success=True,
                    metadata={
                        "status_code": 200,
                        "truncated": len(content) > _MAX_RESPONSE_BYTES,
                    },
                )
            except Exception as exc:
                logger.debug("Rust HTTP request fallback to httpx: %s", exc)

        try:
            t0 = time.time()
            response = httpx.request(
                method,
                url,
                headers=headers,
                content=body,
                timeout=float(timeout),
                follow_redirects=True,
            )
            elapsed_ms = (time.time() - t0) * 1000

            content_type = response.headers.get("content-type", "")
            response_headers = dict(response.headers)

            # Truncate response body if larger than 1 MB
            raw_body = response.text
            truncated = False
            if len(raw_body) > _MAX_RESPONSE_BYTES:
                raw_body = raw_body[:_MAX_RESPONSE_BYTES]
                truncated = True

            content = raw_body
            if truncated:
                content += "\n\n[Response truncated at 1 MB]"

            return ToolResult(
                tool_name="http_request",
                content=content,
                success=True,
                metadata={
                    "status_code": response.status_code,
                    "headers": response_headers,
                    "content_type": content_type,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "truncated": truncated,
                },
            )
        except httpx.TimeoutException as exc:
            return ToolResult(
                tool_name="http_request",
                content=f"Request timed out after {timeout}s: {exc}",
                success=False,
            )
        except httpx.RequestError as exc:
            return ToolResult(
                tool_name="http_request",
                content=f"Request error: {exc}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="http_request",
                content=f"Unexpected error: {exc}",
                success=False,
            )


__all__ = ["HttpRequestTool"]
