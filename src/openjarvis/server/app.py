"""FastAPI application factory for the OpenJarvis API server."""

from __future__ import annotations

import logging
import pathlib
import time
from contextlib import asynccontextmanager
from inspect import isawaitable
from typing import Any

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


async def _cleanup_call(resource: Any, method_name: str, *args: Any) -> None:
    if resource is None:
        return
    method = getattr(resource, method_name, None)
    if method is None:
        return
    result = method(*args)
    if isawaitable(result):
        await result


async def _shutdown_app_resources(app: FastAPI) -> None:
    """Close app-owned resources once, in dependency-safe reverse order."""

    if getattr(app.state, "shutdown_complete", False):
        return
    app.state.shutdown_complete = True

    websocket_shutdown = getattr(app.state, "websocket_shutdown", None)
    if websocket_shutdown is not None:
        try:
            result = websocket_shutdown()
            if isawaitable(result):
                await result
        except Exception:
            logger.debug("WebSocket shutdown failed", exc_info=True)

    browser = getattr(app.state, "browser_session_service", None)
    if browser is not None:
        try:
            for session in tuple(browser.list()):
                try:
                    browser.close(session.session_id)
                except Exception:
                    logger.debug("Owned browser session shutdown failed", exc_info=True)
        except Exception:
            logger.debug("Browser shutdown inventory failed", exc_info=True)

    for client in tuple(getattr(app.state, "_mcp_clients", ())):
        try:
            await _cleanup_call(client, "close")
        except Exception:
            logger.debug("MCP client shutdown failed", exc_info=True)

    if getattr(app.state, "owns_task_runtime", False):
        for attribute, method in (
            ("codex_orchestrator", "close"),
            ("task_store", "close"),
            ("trace_store", "close"),
        ):
            try:
                await _cleanup_call(getattr(app.state, attribute, None), method)
            except Exception:
                logger.debug("%s shutdown failed", attribute, exc_info=True)
    elif getattr(app.state, "owns_trace_store", False):
        try:
            await _cleanup_call(getattr(app.state, "trace_store", None), "close")
        except Exception:
            logger.debug("trace_store shutdown failed", exc_info=True)

    for attribute, method in (
        ("vault_memory_service", "close"),
        ("memory_service", "stop"),
        ("analytics_bridge", "stop"),
        ("analytics_client", "shutdown"),
    ):
        try:
            await _cleanup_call(getattr(app.state, attribute, None), method)
        except Exception:
            logger.debug("%s shutdown failed", attribute, exc_info=True)


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
    memory_service=None,
    vault_memory_service=None,
    speech_backend=None,
    tts_backend=None,
    agent_manager=None,
    agent_scheduler=None,
    trace_store=None,
    task_store=None,
    task_service=None,
    approval_broker=None,
    codex_orchestrator=None,
    recovery_coordinator=None,
    tool_action_service=None,
    website_staging_service=None,
    browser_session_service=None,
    phase7_learning_runtime=None,
    phase7_skill_test_runner=None,
    phase7_healthcheck_runner=None,
    owns_task_runtime: bool = False,
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

    @asynccontextmanager
    async def lifespan(runtime_app: FastAPI):
        runtime_app.state.lifecycle_started = True
        try:
            _restore_sendblue_bindings(runtime_app)
            yield
        finally:
            await _shutdown_app_resources(runtime_app)

    app = FastAPI(
        title="OpenJarvis API",
        description="OpenAI-compatible API server for OpenJarvis",
        version="0.1.0",
        lifespan=lifespan,
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
    app.state.memory_backend = memory_backend
    app.state.memory_service = memory_service
    app.state.vault_memory_service = vault_memory_service
    app.state.speech_backend = speech_backend
    app.state.tts_backend = tts_backend
    app.state.agent_manager = agent_manager
    app.state.agent_scheduler = agent_scheduler
    app.state.task_store = task_store
    app.state.task_service = task_service
    app.state.approval_broker = approval_broker
    app.state.codex_orchestrator = codex_orchestrator
    app.state.recovery_coordinator = recovery_coordinator
    app.state.tool_action_service = tool_action_service
    app.state.website_staging_service = website_staging_service
    app.state.browser_session_service = browser_session_service
    app.state.phase7_learning_runtime = phase7_learning_runtime
    app.state.phase7_skill_test_runner = phase7_skill_test_runner
    app.state.phase7_healthcheck_runner = phase7_healthcheck_runner
    app.state.owns_task_runtime = owns_task_runtime
    app.state.shutdown_complete = False
    app.state.session_start = time.time()
    # Exposed so WebSocket handlers can authenticate the handshake (the HTTP
    # AuthMiddleware never sees WS upgrade requests). Empty = auth disabled.
    app.state.api_key = api_key

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
    app.state.trace_store = trace_store
    app.state.owns_trace_store = False
    if trace_store is None:
        try:
            from openjarvis.core.config import load_config
            from openjarvis.traces.store import TraceStore

            cfg = config if config is not None else load_config()
            if cfg.traces.enabled:
                app.state.trace_store = TraceStore(db_path=cfg.traces.db_path)
                app.state.owns_trace_store = True
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

    except Exception as _exc:
        logger.debug("Analytics init skipped: %s", _exc)

    app.include_router(router)
    app.include_router(dashboard_router)
    app.include_router(comparison_router)
    app.include_router(create_connectors_router())
    app.include_router(create_digest_router())
    app.include_router(upload_router)
    app.include_router(research_router)
    app.include_router(analytics_router)
    include_all_routes(app)

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
