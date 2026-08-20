"""Shared async-HTTP plumbing for engines that stream over httpx.

Home of the pieces the OpenAI-compat and Ollama engines were each hand-rolling:
the async-client factory (with the configured timeout applied), a cached
long-lived client so consecutive streams reuse pooled connections instead of
paying a fresh TCP/TLS handshake per turn, the transport-error set that maps to
``EngineConnectionError``, and the non-2xx → engine-error translation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import NoReturn

import httpx

from openjarvis.engine._base import (
    EngineConnectionError,
    EngineContextLengthError,
    looks_like_context_length_error,
)

logger = logging.getLogger(__name__)

# Transport failures that map to EngineConnectionError on the streaming paths.
# ``RemoteProtocolError``/``ReadError`` cover a server dying MID-STREAM (peer
# closed between tokens); a wedged read trips the configured timeout
# (TimeoutException). Kept exactly this narrow on purpose:
# ``asyncio.CancelledError``/``GeneratorExit`` are NOT ``httpx.TransportError``
# subclasses and must keep propagating for correct cancellation.
STREAM_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)

_CONTEXT_LENGTH_USER_MESSAGE = (
    "The conversation is too long for the model's context window. "
    "Start a new chat or shorten the conversation, then try again."
)


class AsyncHTTPEngineMixin:
    """Async streaming plumbing shared by httpx-backed engines.

    Expects the engine to provide ``engine_id``, ``_host``, ``_timeout``, an
    ``_async_transport`` test seam (``httpx.MockTransport`` in tests, ``None``
    in production), and optionally ``_headers``.
    """

    engine_id: str
    _host: str
    _timeout: float
    _async_transport: httpx.AsyncBaseTransport | None

    # Set True by engines whose upstream reports context-window overflows in
    # 400 bodies (OpenAI-compat servers). Ollama has no such signal.
    _stream_400_signals_context_length: bool = False

    # Lazily-created shared client (and the loop it belongs to). Class-level
    # ``None`` defaults keep engine ``__init__``s free of mixin bookkeeping.
    _async_client: httpx.AsyncClient | None = None
    _async_client_loop: asyncio.AbstractEventLoop | None = None

    def _make_async_client(self) -> httpx.AsyncClient:
        """Build an async client that honours the configured timeout."""
        return httpx.AsyncClient(
            base_url=self._host,
            timeout=self._timeout,
            headers=getattr(self, "_headers", None),
            transport=self._async_transport,
        )

    def _get_async_client(self) -> httpx.AsyncClient:
        """Return the shared async client for the running event loop.

        Reusing one client across calls preserves connection pooling — without
        it every conversation turn pays a fresh TCP (and TLS) handshake. The
        client is cached per event loop: pooled connections die with their
        loop, so CLI flows that run ``asyncio.run()`` per turn transparently
        get a fresh client while a long-lived server loop keeps one pool.
        """
        loop = asyncio.get_running_loop()
        client = self._async_client
        if client is None or client.is_closed or self._async_client_loop is not loop:
            # Any previous client belonged to a finished loop; its pooled
            # connections are already dead, so just drop the reference.
            client = self._make_async_client()
            self._async_client = client
            self._async_client_loop = loop
        return client

    def _close_async_client(self) -> None:
        """Best-effort close of the shared async client (for ``close()``)."""
        client = self._async_client
        loop = self._async_client_loop
        self._async_client = None
        self._async_client_loop = None
        if client is None or client.is_closed:
            return
        try:
            if loop is not None and not loop.is_closed():
                if loop.is_running():
                    loop.create_task(client.aclose())
                else:
                    loop.run_until_complete(client.aclose())
        except Exception:  # noqa: BLE001 — cleanup must never mask the close
            logger.debug("Async client did not close cleanly", exc_info=True)

    def _raise_stream_http_error(self, status: int, detail: str) -> NoReturn:
        """Map a non-success streaming HTTP response to a clean engine error."""
        detail = (detail or "").strip()
        if (
            status == 400
            and self._stream_400_signals_context_length
            and looks_like_context_length_error(detail)
        ):
            raise EngineContextLengthError(_CONTEXT_LENGTH_USER_MESSAGE)
        detail_suffix = f": {detail}" if detail else ""
        raise EngineConnectionError(
            f"{self.engine_id} engine at {self._host} returned HTTP "
            f"{status}{detail_suffix}"
        )


__all__ = ["AsyncHTTPEngineMixin", "STREAM_TRANSPORT_ERRORS"]
