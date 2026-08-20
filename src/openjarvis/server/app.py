"""FastAPI application factory for the OpenJarvis API server."""

from __future__ import annotations

import logging
import pathlib
import threading
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from openjarvis.server.analytics_routes import router as analytics_router
from openjarvis.server.api_routes import include_all_routes
from openjarvis.server.comparison import comparison_router
from openjarvis.server.connectors_router import create_connectors_router
from openjarvis.server.dashboard import dashboard_router
from openjarvis.server.digest_routes import create_digest_router
from openjarvis.server.research_router import router as research_router
from openjarvis.server.routes import router
from openjarvis.server.upload_router import router as upload_router

logger = logging.getLogger(__name__)
_MANAGED_SHUTDOWN_GRACE_SECONDS = 0.25
_MANAGED_SHUTDOWN_DRAIN_SECONDS = 10.0


def _restore_sendblue_bindings(app: FastAPI) -> None:
    """Restore SendBlue channel bindings from the database on startup.

    If a SendBlue binding was created via the Messaging tab and the server
    restarts, this ensures the ChannelBridge + DeepResearchAgent are wired
    up so incoming webhooks continue to work.
    """
    try:
        mgr = getattr(app.state, "agent_manager", None)
        if mgr is None:
            return

        # Check all agents for sendblue bindings
        for agent in mgr.list_agents():
            agent_id = agent.get("id", agent.get("agent_id", ""))
            bindings = mgr.list_channel_bindings(agent_id)
            for b in bindings:
                if b.get("channel_type") != "sendblue":
                    continue
                config = b.get("config", {})
                api_key_id = config.get("api_key_id", "")
                api_secret_key = config.get("api_secret_key", "")
                from_number = config.get("from_number", "")
                if not api_key_id or not api_secret_key:
                    continue

                from openjarvis.channels.sendblue import SendBlueChannel

                sb = SendBlueChannel(
                    api_key_id=api_key_id,
                    api_secret_key=api_secret_key,
                    from_number=from_number,
                )
                sb.connect()
                app.state.sendblue_channel = sb

                # Create ChannelBridge if none exists
                bridge = getattr(app.state, "channel_bridge", None)
                if bridge and hasattr(bridge, "_channels"):
                    bridge._channels["sendblue"] = sb
                else:
                    from openjarvis.server.channel_bridge import ChannelBridge
                    from openjarvis.server.session_store import SessionStore

                    session_store = SessionStore()
                    engine = getattr(app.state, "engine", None)
                    dr_agent = None
                    if engine:
                        from openjarvis.server.agent_manager_routes import (
                            _build_deep_research_tools,
                        )

                        tools = _build_deep_research_tools(engine=engine, model="")
                        if tools:
                            from openjarvis.agents.deep_research import (
                                DeepResearchAgent,
                            )

                            model_name = getattr(app.state, "model", "") or getattr(
                                engine, "_model", ""
                            )
                            dr_agent = DeepResearchAgent(
                                engine=engine,
                                model=model_name,
                                tools=tools,
                            )

                    bus = getattr(app.state, "bus", None)
                    if bus is None:
                        from openjarvis.core.events import EventBus

                        bus = EventBus()

                    app.state.channel_bridge = ChannelBridge(
                        channels={"sendblue": sb},
                        session_store=session_store,
                        bus=bus,
                        agent_manager=mgr,
                        deep_research_agent=dr_agent,
                    )

                logger.info(
                    "Restored SendBlue channel binding: %s",
                    from_number,
                )
                return  # Only need one SendBlue binding
    except Exception as exc:
        logger.debug("SendBlue binding restore skipped: %s", exc)


# No-cache headers applied to static file responses
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


class _NoCacheStaticFiles(StaticFiles):
    """StaticFiles subclass that adds no-cache headers to every response."""

    async def __call__(self, scope, receive, send):
        async def _send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = [(k.encode(), v.encode()) for k, v in _NO_CACHE_HEADERS.items()]
                # Remove etag and last-modified
                existing = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in (b"etag", b"last-modified")
                ]
                message = {**message, "headers": existing + extra}
            await send(message)

        await super().__call__(scope, receive, _send_with_headers)


def create_app(
    engine,
    model: str,
    *,
    agent=None,
    bus=None,
    engine_name: str = "",
    agent_name: str = "",
    channel_bridge=None,
    config=None,
    memory_backend=None,
    own_memory_backend: bool = False,
    memory_service=None,
    speech_backend=None,
    agent_manager=None,
    agent_scheduler=None,
    mcp_tools=None,
    mcp_clients=None,
    api_key: str = "",
    webhook_config: dict | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    engine:
        The inference engine to use for completions.
    model:
        Default model name.
    agent:
        Optional agent instance for agent-mode completions.
    bus:
        Optional event bus for telemetry.
    channel_bridge:
        Optional channel bridge for multi-platform messaging.
    config:
        Optional JarvisConfig for other settings.
    """
    app = FastAPI(
        title="OpenJarvis API",
        description="OpenAI-compatible API server for OpenJarvis",
        version="0.1.0",
    )

    from fastapi.middleware.cors import CORSMiddleware

    _origins = (
        cors_origins
        if cors_origins is not None
        else [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            # Tauri 2 production webview origins:
            #   macOS / Linux / iOS  -> tauri://localhost
            #   Windows / Android    -> http://tauri.localhost (default),
            #                           https://tauri.localhost when
            #                           windows.useHttpsScheme is enabled
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )
    # Store dependencies in app state
    app.state.engine = engine
    app.state.model = model
    app.state.agent = agent
    app.state.bus = bus
    app.state.engine_name = engine_name
    app.state.agent_name = agent_name or (
        getattr(agent, "agent_id", None) if agent else None
    )
    app.state.channel_bridge = channel_bridge
    app.state.config = config
    app.state._memory_backend_lock = threading.Lock()
    app.state.memory_backend = memory_backend
    app.state._owns_memory_backend = bool(own_memory_backend)
    app.state.memory_service = memory_service
    app.state.speech_backend = speech_backend
    app.state.agent_manager = agent_manager
    app.state.agent_scheduler = agent_scheduler
    app.state.mcp_tools = list(mcp_tools or [])
    app.state._mcp_discovery_lock = threading.Lock()
    app.state._mcp_clients_lock = threading.Lock()
    app.state._mcp_clients = list(mcp_clients or [])
    app.state._managed_worker_lock = threading.Lock()
    app.state._managed_workers: set[threading.Thread] = set()
    app.state._managed_runtime_stopping = False
    app.state.session_start = time.time()
    # Exposed so WebSocket handlers can authenticate the handshake (the HTTP
    # AuthMiddleware never sees WS upgrade requests). Empty = auth disabled.
    app.state.api_key = api_key

    @app.on_event("shutdown")
    async def _shutdown_managed_runtime() -> None:
        # Quiesce every producer before touching the shared MCP pool. Route
        # workers are registered under this lock, so none can slip in after
        # the snapshot. The scheduler has a two-phase stop because closing an
        # MCP transport may be what releases an in-flight tick.
        with app.state._managed_worker_lock:
            app.state._managed_runtime_stopping = True
            managed_workers = list(app.state._managed_workers)

        # Stop external listener threads before draining ticks or closing the
        # shared MCP pool. Channel callbacks are wired to that same pool by
        # ``serve`` and otherwise could race teardown or survive app restart.
        channel_bridge = getattr(app.state, "channel_bridge", None)
        disconnect_channels = getattr(channel_bridge, "disconnect", None)
        if callable(disconnect_channels):
            try:
                disconnect_channels()
            except Exception:
                logger.debug("Channel bridge shutdown failed", exc_info=True)

        def _join_workers(timeout: float) -> None:
            deadline = time.monotonic() + timeout
            for thread in managed_workers:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                thread.join(timeout=remaining)

        scheduler = getattr(app.state, "agent_scheduler", None)
        scheduler_wait = None
        scheduler_drained = True
        if scheduler is not None:
            try:
                request_stop = getattr(scheduler, "request_stop", None)
                wait_stopped = getattr(scheduler, "wait_stopped", None)
                if callable(request_stop) and callable(wait_stopped):
                    request_stop()
                    scheduler_wait = wait_stopped
                    scheduler_drained = bool(
                        wait_stopped(timeout=_MANAGED_SHUTDOWN_GRACE_SECONDS)
                    )
                else:
                    scheduler.stop()
                    scheduler_drained = not bool(
                        getattr(scheduler, "is_running", False)
                    )
            except Exception:
                scheduler_drained = False
                logger.debug("Agent scheduler shutdown failed", exc_info=True)

        # Give normal work a brief chance to finish before cancellation.
        _join_workers(timeout=_MANAGED_SHUTDOWN_GRACE_SECONDS)
        with app.state._mcp_clients_lock:
            mcp_clients_to_close = list(app.state._mcp_clients)
        for client in mcp_clients_to_close:
            try:
                client.close()
            except Exception:
                logger.debug("MCP client shutdown failed", exc_info=True)

        # Transport closure interrupts blocked MCP reads. Drain the workers a
        # second time so shutdown does not return while they still own runtime
        # state. Any stragglers can no longer issue transport requests because
        # MCPClient marks itself closed before closing its transport.
        if scheduler_wait is not None:
            try:
                scheduler_drained = bool(
                    scheduler_wait(timeout=_MANAGED_SHUTDOWN_DRAIN_SECONDS)
                )
            except Exception:
                scheduler_drained = False
                logger.debug("Agent scheduler drain failed", exc_info=True)
        _join_workers(timeout=_MANAGED_SHUTDOWN_DRAIN_SECONDS)
        alive = [thread.name for thread in managed_workers if thread.is_alive()]
        if alive:
            logger.warning("Managed workers did not stop during shutdown: %s", alive)

        # A backend created by ``serve`` or lazily by a managed route belongs
        # to this app process. Close it only after every tracked consumer has
        # been drained; injected/borrowed backends remain the caller's concern.
        owned_memory_backend = None
        runtime_drained = scheduler_drained and not alive
        if runtime_drained:
            with app.state._memory_backend_lock:
                if app.state._owns_memory_backend:
                    owned_memory_backend = app.state.memory_backend
                    app.state.memory_backend = None
                    app.state._owns_memory_backend = False
        else:
            # A live worker may itself hold _memory_backend_lock while opening
            # the backend. Respect the bounded shutdown deadline: do not wait
            # on that lock or mutate ownership until every consumer is gone.
            logger.warning(
                "Skipping memory backend cleanup because managed runtime "
                "consumers did not stop"
            )
        close_memory = getattr(owned_memory_backend, "close", None)
        if callable(close_memory):
            try:
                close_memory()
            except Exception:
                logger.debug("Memory backend shutdown failed", exc_info=True)

    # Wire up trace store if traces are enabled.
    #
    # We deliberately do NOT subscribe the trace store to the bus. The chat
    # endpoints persist through a TraceCollector that calls store.save()
    # directly (mirroring system/orchestrator.py), and the collector ALSO
    # publishes TRACE_COMPLETE. A store subscribed to that same bus would
    # therefore save every agent trace twice — the second INSERT hitting the
    # UNIQUE constraint on trace_id (a 500 on every completion). Keeping the
    # collector the single writer is what makes the dual code path safe; only
    # the telemetry store is bus-subscribed (see system/builder.py).
    app.state.trace_store = None
    try:
        from openjarvis.core.config import load_config
        from openjarvis.traces.store import TraceStore

        cfg = config if config is not None else load_config()
        if cfg.traces.enabled:
            app.state.trace_store = TraceStore(db_path=cfg.traces.db_path)
    except Exception:
        pass  # traces are optional; don't block server startup

    # Wire up external analytics if enabled (PostHog) — never block startup.
    # Note: we do NOT fire app_opened here. The frontend owns that event
    # because "server started" (this code path) is not the same as "user
    # opened the app" — the server can run headless via cron, daemons,
    # or test suites.
    app.state.analytics_client = None
    app.state.analytics_bridge = None
    try:
        from openjarvis.analytics import (
            AnalyticsClient,
            EventBridge,
            is_analytics_enabled,
        )
        from openjarvis.core.config import load_config

        _cfg = config if config is not None else load_config()
        if is_analytics_enabled(_cfg.analytics):
            _client = AnalyticsClient(_cfg.analytics)
            app.state.analytics_client = _client
            _bus_ref = getattr(app.state, "bus", None)
            if _bus_ref is not None:
                _bridge = EventBridge(_bus_ref, _client)
                _bridge.start()
                app.state.analytics_bridge = _bridge

            @app.on_event("shutdown")
            async def _shutdown_analytics() -> None:
                bridge = getattr(app.state, "analytics_bridge", None)
                if bridge is not None:
                    try:
                        bridge.stop()
                    except Exception:
                        pass
                client = getattr(app.state, "analytics_client", None)
                if client is not None:
                    try:
                        client.shutdown()
                    except Exception:
                        pass
    except Exception as _exc:
        logger.debug("Analytics init skipped: %s", _exc)

    # Stop the background memory service cleanly when the server shuts down.
    if memory_service is not None:

        @app.on_event("shutdown")
        async def _shutdown_memory_service() -> None:
            svc = getattr(app.state, "memory_service", None)
            if svc is not None:
                try:
                    svc.stop()
                except Exception:
                    pass

    app.include_router(router)
    app.include_router(dashboard_router)
    app.include_router(comparison_router)
    app.include_router(create_connectors_router())
    app.include_router(create_digest_router())
    app.include_router(upload_router)
    app.include_router(research_router)
    app.include_router(analytics_router)
    include_all_routes(app)

    # Restore SendBlue channel bindings from database on startup
    _restore_sendblue_bindings(app)

    # Add security headers middleware
    try:
        from openjarvis.server.middleware import create_security_middleware

        middleware_cls = create_security_middleware()
        if middleware_cls is not None:
            app.add_middleware(middleware_cls)
    except Exception as exc:
        logger.debug("Security middleware init skipped: %s", exc)

    # API key authentication middleware
    if api_key:
        try:
            from openjarvis.server.auth_middleware import AuthMiddleware

            app.add_middleware(AuthMiddleware, api_key=api_key)
        except Exception as exc:
            logger.debug("Auth middleware init skipped: %s", exc)

    # Register CORS last so it is the outermost middleware. In addition to
    # handling preflights, this ensures browser clients can read 401 responses
    # produced directly by AuthMiddleware instead of seeing an opaque CORS
    # network error.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount webhook routes (always — SendBlue may be configured dynamically)
    if webhook_config:
        try:
            from openjarvis.server.webhook_routes import (
                create_webhook_router,
            )

            webhook_router = create_webhook_router(
                bridge=channel_bridge,
                twilio_auth_token=webhook_config.get("twilio_auth_token", ""),
                bluebubbles_password=webhook_config.get("bluebubbles_password", ""),
                whatsapp_verify_token=webhook_config.get("whatsapp_verify_token", ""),
                whatsapp_app_secret=webhook_config.get("whatsapp_app_secret", ""),
            )
            app.include_router(webhook_router)
        except Exception as exc:
            logger.debug("Webhook routes init skipped: %s", exc)

    # Serve static frontend assets if the static/ directory exists
    static_dir = pathlib.Path(__file__).parent / "static"
    if static_dir.is_dir():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                _NoCacheStaticFiles(directory=assets_dir),
                name="static-assets",
            )

        @app.get("/{full_path:path}")
        async def spa_catch_all(full_path: str):
            """Serve static files directly, fall back to index.html for SPA routes."""
            if full_path:
                candidate = (static_dir / full_path).resolve()
                # Path traversal prevention
                resolved_root = static_dir.resolve()
                if candidate.is_relative_to(resolved_root) and candidate.is_file():
                    return FileResponse(candidate, headers=_NO_CACHE_HEADERS)
            return FileResponse(
                static_dir / "index.html",
                headers=_NO_CACHE_HEADERS,
            )

    return app


__all__ = ["create_app"]
