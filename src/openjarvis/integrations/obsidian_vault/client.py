"""Sync-friendly wrapper around the obsidian-vault MCP/SSE service.

The Railway-hosted ``obsidian-vault`` service exposes 23 vault tools
over the MCP Server-Sent-Events transport on port 22360. This module
provides a sync facade so the rest of OpenJarvis (memory backends,
function-calling tools, ingestion connectors) can call vault operations
without each call site rebuilding async glue.

Design notes
------------
* The MCP Python SDK (``mcp``) is an *optional* dependency
  (``pip install -e .[memory-obsidian]``). When the package is missing,
  every method raises :class:`VaultUnavailableError` — callers should
  catch this and degrade gracefully (return empty results, log, etc.)
  rather than propagating into the request path.
* Each public method opens a fresh MCP session per call. This is
  ~200ms per round-trip vs ~5ms for a persistent connection, but keeps
  the implementation thread-safe and stateless. v2 may add a singleton
  background-loop session for hot-path tools like memory retrieve.
* Connection failures (vault container down, network partition, DNS
  miss) raise :class:`VaultUnavailableError`. Logical failures
  (missing note, malformed args) propagate the upstream error.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_VAULT_URL = "http://obsidian-vault.railway.internal:22360"


class VaultUnavailableError(RuntimeError):
    """Raised when the vault service is unreachable or the MCP SDK is missing."""


def _resolve_url(url: Optional[str]) -> str:
    if url:
        return url.rstrip("/")
    return os.environ.get("OBSIDIAN_VAULT_URL", DEFAULT_VAULT_URL).rstrip("/")


class ObsidianVaultClient:
    """Thread-safe sync wrapper around the obsidian-vault MCP service.

    Parameters
    ----------
    url:
        Base URL of the MCP service. Defaults to the value of
        ``OBSIDIAN_VAULT_URL`` env var, falling back to the Railway
        internal hostname.
    request_timeout_s:
        Per-call timeout including session establishment. The MCP SDK
        does not expose a per-call timeout natively, so we wrap each
        operation in ``asyncio.wait_for``.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        *,
        request_timeout_s: float = 30.0,
    ) -> None:
        self._url = _resolve_url(url)
        self._sse_url = f"{self._url}/sse"
        self._timeout = request_timeout_s
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal: async dispatcher
    # ------------------------------------------------------------------

    async def _async_call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Open an MCP session, call one tool, return the unwrapped result."""
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as exc:  # pragma: no cover — depends on optional dep
            raise VaultUnavailableError(
                "mcp package not installed; "
                "install with `pip install -e .[memory-obsidian]`"
            ) from exc

        try:
            async with sse_client(self._sse_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
        except Exception as exc:
            raise VaultUnavailableError(
                f"vault MCP call failed at {self._sse_url}: {exc!r}"
            ) from exc

        # Unwrap MCP CallToolResult: extract first text-content block,
        # or return the raw structured content if present.
        if getattr(result, "isError", False):
            raise VaultUnavailableError(
                f"vault tool '{tool_name}' returned isError=True: {result}"
            )
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        contents = getattr(result, "content", None) or []
        for block in contents:
            text = getattr(block, "text", None)
            if text is not None:
                return text
        return None

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Run :meth:`_async_call` on a fresh event loop with a timeout."""
        with self._lock:
            try:
                return asyncio.run(
                    asyncio.wait_for(
                        self._async_call(tool_name, arguments),
                        timeout=self._timeout,
                    )
                )
            except asyncio.TimeoutError as exc:
                raise VaultUnavailableError(
                    f"vault tool '{tool_name}' timed out after {self._timeout}s"
                ) from exc

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """Best-effort liveness check: call ``get_vault_info`` with a short timeout."""
        try:
            self._call("get_vault_info", {})
            return True
        except VaultUnavailableError as exc:
            logger.info("Obsidian vault unhealthy: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def list_directory(self, path: str = "") -> Any:
        return self._call("list_directory", {"path": path} if path else {})

    def read_file(self, path: str) -> str:
        result = self._call("read_file", {"path": path})
        return result or ""

    def search_files(self, query: str, max_results: int = 50) -> Any:
        return self._call(
            "search_files",
            {"query": query, "max_results": max_results},
        )

    def search_with_filters(
        self,
        *,
        content_query: Optional[str] = None,
        tag: Optional[str] = None,
        path_prefix: Optional[str] = None,
        frontmatter_key: Optional[str] = None,
        frontmatter_value: Optional[str] = None,
    ) -> Any:
        args: dict[str, Any] = {}
        if content_query:
            args["content_query"] = content_query
        if tag:
            args["tag"] = tag
        if path_prefix:
            args["path_prefix"] = path_prefix
        if frontmatter_key:
            args["frontmatter_key"] = frontmatter_key
        if frontmatter_value:
            args["frontmatter_value"] = frontmatter_value
        return self._call("search_with_filters", args)

    def get_vault_info(self) -> Any:
        return self._call("get_vault_info", {})

    def get_vault_summary(self) -> Any:
        return self._call("get_vault_summary", {})

    def get_recent_notes(self, n: int = 10) -> Any:
        return self._call("get_recent_notes", {"n": n})

    def get_backlinks(self, path: str) -> Any:
        return self._call("get_backlinks", {"path": path})

    def get_note_metadata(self, path: str) -> Any:
        return self._call("get_note_metadata", {"path": path})

    def get_note_links(self, path: str) -> Any:
        return self._call("get_note_links", {"path": path})

    def list_folders(self) -> Any:
        return self._call("list_folders", {})

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str) -> Any:
        return self._call("write_file", {"path": path, "content": content})

    def append_to_file(self, path: str, content: str) -> Any:
        return self._call("append_to_file", {"path": path, "content": content})

    def delete_file(self, path: str) -> Any:
        return self._call("delete_file", {"path": path})

    def update_note_frontmatter(
        self, path: str, fields: dict[str, Any], *, merge: bool = True
    ) -> Any:
        return self._call(
            "update_note_frontmatter",
            {"path": path, "fields": fields, "merge": merge},
        )


# ---------------------------------------------------------------------------
# Module-level default client (lazy singleton)
# ---------------------------------------------------------------------------

_default_client: Optional[ObsidianVaultClient] = None
_default_lock = threading.Lock()


def get_default_client() -> ObsidianVaultClient:
    """Return a process-wide :class:`ObsidianVaultClient` singleton.

    The instance is created lazily on first access and uses the
    ``OBSIDIAN_VAULT_URL`` env var (or the Railway internal default).
    """
    global _default_client
    if _default_client is None:
        with _default_lock:
            if _default_client is None:
                _default_client = ObsidianVaultClient()
    return _default_client


__all__ = [
    "DEFAULT_VAULT_URL",
    "ObsidianVaultClient",
    "VaultUnavailableError",
    "get_default_client",
]
