"""Official MCP Python SDK runtime behind OpenJarvis's synchronous facade.

OpenJarvis calls MCP servers from synchronous tool code, but the official SDK
is asynchronous and its transports (``stdio_client``,
``streamablehttp_client``) are anyio task-scoped: the context that entered them
must also exit them.  ``MCPRuntime`` therefore owns exactly one event-loop
thread and one long-lived *runner task* that enters the transport and the
``ClientSession`` and then parks until close.  Individual requests are
submitted onto the same loop as separate tasks, which the SDK's ``BaseSession``
supports, and which lets a single in-flight request be cancelled without
tearing down the session.

Nothing here logs commands, environments, tokens, profile paths, tool
arguments, or tool results.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Callable, Optional

from openjarvis.mcp.protocol import MCPError

# MCP tools routinely wrap long-running work (browser navigation, scans).
# Matches the ToolSpec timeout used by MCPClient.list_tools().
REQUEST_TIMEOUT = timedelta(seconds=600)

_CLOSE_TIMEOUT_SECONDS = 5.0


def _default_session_factory(*args: Any, **kwargs: Any) -> Any:
    from mcp.types import Implementation

    from mcp import ClientSession

    kwargs.setdefault(
        "client_info", Implementation(name="openjarvis", version="0.1.0")
    )
    return ClientSession(*args, **kwargs)


def _as_mcp_error(exc: BaseException) -> Optional[MCPError]:
    """Translate an official SDK protocol error into OpenJarvis's ``MCPError``."""
    try:
        from mcp.shared.exceptions import McpError
    except ImportError:  # pragma: no cover — mcp is a hard dependency
        return None
    if not isinstance(exc, McpError):
        return None
    error = exc.error
    return MCPError(
        code=getattr(error, "code", -1),
        message=getattr(error, "message", str(exc)),
        data=getattr(error, "data", None),
    )


class MCPRuntime:
    """Synchronous facade over one official SDK ``ClientSession``.

    Parameters
    ----------
    transport:
        A transport exposing ``sdk_client()`` — an async context manager that
        yields the SDK read/write streams.
    session_factory:
        Constructor for the SDK session; injected in tests.
    """

    def __init__(
        self,
        transport: Any,
        *,
        session_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._transport = transport
        self._session_factory = session_factory or _default_session_factory

        self._state_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active: Any = None

        self._session: Any = None
        self._initialize_result: dict[str, Any] = {}
        self._start_done = threading.Event()
        self._start_error: BaseException | None = None
        self._stop_event: asyncio.Event | None = None
        self._runner: Any = None
        self._closed = False

        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="openjarvis-mcp-runtime",
            daemon=True,
        )
        self._thread.start()
        self._loop_ready.wait()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def loop_thread_ident(self) -> int | None:
        """Identity of the thread owning the SDK event loop."""
        return self._thread.ident

    @property
    def thread_is_alive(self) -> bool:
        return self._thread.is_alive()

    # ------------------------------------------------------------------
    # Public synchronous API
    # ------------------------------------------------------------------

    def initialize(self) -> dict[str, Any]:
        """Return the server's initialize result, starting the session once."""
        self._ensure_started()
        return dict(self._initialize_result)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return every advertised tool, following pagination cursors."""
        return self._request(self._list_tools)

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Invoke one tool and return the standard MCP result mapping."""
        return self._request(
            lambda session: self._call_tool(session, name, arguments or {})
        )

    def cancel_active_call(self) -> None:
        """Cancel the in-flight request, if any. Safe to call when idle."""
        with self._active_lock:
            future = self._active
        if future is not None:
            future.cancel()

    def close(self) -> None:
        """Tear the session, transport, loop, and thread down exactly once."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            runner = self._runner
            stop_event = self._stop_event

        if runner is not None and stop_event is not None:
            self._loop.call_soon_threadsafe(stop_event.set)
            try:
                runner.result(timeout=_CLOSE_TIMEOUT_SECONDS)
            except BaseException:  # noqa: BLE001 — teardown must not raise
                pass

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=_CLOSE_TIMEOUT_SECONDS)
        if not self._thread.is_alive():
            self._loop.close()

    # ------------------------------------------------------------------
    # Loop thread
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        try:
            self._loop.run_forever()
        finally:
            asyncio.set_event_loop(None)

    def _ensure_started(self) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("MCP runtime is closed")
            if self._runner is None:
                self._stop_event = asyncio.Event()
                self._runner = asyncio.run_coroutine_threadsafe(
                    self._session_runner(), self._loop
                )
        self._start_done.wait()
        if self._start_error is not None:
            raise self._start_error

    async def _session_runner(self) -> None:
        """Enter and exit the SDK transport/session from a single task."""
        stop_event = self._stop_event
        assert stop_event is not None
        try:
            async with AsyncExitStack() as stack:
                streams = await stack.enter_async_context(self._transport.sdk_client())
                # stdio yields (read, write); Streamable HTTP adds a session-id
                # callback as a third member.
                read_stream, write_stream = streams[0], streams[1]
                session = await stack.enter_async_context(
                    self._session_factory(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=REQUEST_TIMEOUT,
                    )
                )
                result = await session.initialize()
                self._initialize_result = result.model_dump(
                    by_alias=True, exclude_none=True
                )
                self._session = session
                self._start_done.set()
                await stop_event.wait()
        except BaseException as exc:  # noqa: BLE001 — surfaced to the caller
            if self._start_error is None:
                self._start_error = _as_mcp_error(exc) or exc
        finally:
            self._session = None
            self._start_done.set()

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    def _request(self, make_coroutine: Callable[[Any], Any]) -> Any:
        self._ensure_started()
        session = self._session
        if session is None:
            raise RuntimeError("MCP session is not available")

        future = asyncio.run_coroutine_threadsafe(make_coroutine(session), self._loop)
        with self._active_lock:
            self._active = future
        try:
            return future.result()
        except BaseException as exc:
            mapped = _as_mcp_error(exc)
            if mapped is not None:
                raise mapped from exc
            raise
        finally:
            with self._active_lock:
                if self._active is future:
                    self._active = None

    async def _list_tools(self, session: Any) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            result = await session.list_tools(cursor=cursor)
            tools.extend(
                tool.model_dump(by_alias=True, exclude_none=True)
                for tool in result.tools
            )
            cursor = getattr(result, "nextCursor", None)
            if not cursor:
                return tools

    async def _call_tool(
        self, session: Any, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        result = await session.call_tool(
            name,
            arguments,
            read_timeout_seconds=REQUEST_TIMEOUT,
        )
        return result.model_dump(by_alias=True, exclude_none=True)


__all__ = ["MCPRuntime", "REQUEST_TIMEOUT"]
