"""FastAPI router for /v1/connectors — connector management endpoints."""

from __future__ import annotations

import logging
import threading
from functools import wraps
from typing import TYPE_CHECKING, Any, Dict, Optional

# ``Request`` must be importable at *module* scope so that FastAPI can resolve
# the stringized ``request: Request`` annotations on the OAuth endpoints below.
# Because this module uses ``from __future__ import annotations``, every
# annotation is a string that FastAPI evaluates against the module globals; a
# ``Request`` imported only inside ``create_connectors_router()`` is invisible
# there, which makes FastAPI mistake ``request`` for a required *query* param
# (HTTP 422 on /oauth/start) or inject ``None`` (AttributeError on
# /oauth/callback). Keep this import at top level. See issue #512.
if TYPE_CHECKING:
    from starlette.requests import Request
else:
    try:
        from starlette.requests import Request
    except ImportError:  # starlette ships with fastapi; absent only without it
        Request = Any  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Module-level cache of connector instances (keyed by connector_id).
_instances: Dict[str, Any] = {}
_SYNC_STOP_TIMEOUT_SECONDS = 5.0


def _knowledge_sources(connector_id: str, connector: Any = None) -> tuple[str, ...]:
    """Return the KnowledgeStore source values owned by a connector."""
    if connector is not None and not isinstance(connector, type):
        getter = getattr(connector, "knowledge_sources", None)
        if callable(getter):
            return tuple(getter())
    explicit = getattr(connector, "indexed_sources", ())
    return tuple(explicit) if explicit else (connector_id,)


def _ensure_connectors_registered() -> None:
    """Ensure ConnectorRegistry is populated.

    If the registry has been cleared (e.g. by test fixtures) but connector
    modules are already cached in sys.modules, reload each submodule to
    re-execute their @ConnectorRegistry.register decorators.
    """
    import importlib
    import sys

    from openjarvis.core.registry import ConnectorRegistry

    # First, try a normal import (works if modules haven't been imported yet).
    try:
        import openjarvis.connectors  # noqa: F401
    except Exception:
        pass

    # If the registry is still empty, reload individual connector submodules
    # that are already present in sys.modules.
    if not ConnectorRegistry.keys():
        for mod_name in list(sys.modules):
            if (
                mod_name.startswith("openjarvis.connectors.")
                and not mod_name.endswith("_stubs")
                and not mod_name.endswith("pipeline")
                and not mod_name.endswith("store")
                and not mod_name.endswith("chunker")
                and not mod_name.endswith("retriever")
                and not mod_name.endswith("sync_engine")
                and not mod_name.endswith("oauth")
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Pydantic request model — defined at module level so FastAPI can resolve
# the type annotation correctly when injecting request bodies.
# ---------------------------------------------------------------------------

try:
    from pydantic import BaseModel as _BaseModel

    class ConnectRequest(_BaseModel):
        """Credentials / connection parameters for a connector."""

        path: Optional[str] = None
        token: Optional[str] = None
        code: Optional[str] = None
        email: Optional[str] = None
        password: Optional[str] = None
        # Connector-specific, non-secret setup values.  Keep credentials in
        # the dedicated fields above so callers do not accidentally log them
        # together with ordinary configuration.
        config: Optional[Dict[str, Any]] = None
        host: Optional[str] = None
        port: Optional[int] = None
        security: Optional[str] = None

except ImportError:
    ConnectRequest = None  # type: ignore[assignment,misc]


def create_connectors_router():
    """Return an APIRouter with /connectors endpoints.

    Importing FastAPI inside the factory avoids a hard import-time
    dependency and mirrors the pattern used by other optional routers in
    this package.
    """
    try:
        from fastapi import APIRouter, HTTPException
    except ImportError as exc:
        raise ImportError(
            "fastapi and pydantic are required for the connectors router"
        ) from exc

    if ConnectRequest is None:
        raise ImportError("pydantic is required for the connectors router")

    from openjarvis.core.registry import ConnectorRegistry

    router = APIRouter(prefix="/v1/connectors", tags=["connectors"])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create(connector_id: str) -> Any:
        """Return a cached connector instance, creating it if needed."""
        if connector_id not in _instances:
            cls = ConnectorRegistry.get(connector_id)
            _instances[connector_id] = cls()
        return _instances[connector_id]

    def _connector_summary(connector_id: str, instance: Any) -> Dict[str, Any]:
        """Build the dict returned by GET /connectors."""
        chunks = 0
        try:
            from openjarvis.connectors.store import KnowledgeStore

            sources = _knowledge_sources(connector_id, instance)
            placeholders = ", ".join("?" for _ in sources)
            with KnowledgeStore() as store:
                rows = store._conn.execute(
                    f"SELECT COUNT(*) FROM knowledge_chunks "
                    f"WHERE source IN ({placeholders})",
                    sources,
                ).fetchone()
                chunks = rows[0] if rows else 0
        except Exception:
            pass

        return {
            "connector_id": connector_id,
            "display_name": getattr(instance, "display_name", connector_id),
            "auth_type": getattr(instance, "auth_type", "unknown"),
            "connected": instance.is_connected(),
            "chunks": chunks,
        }

    def _maybe_oauth_client_pair(
        connector_id: str, req: ConnectRequest
    ) -> Optional[Dict[str, Any]]:
        """Handle a pasted ``client_id:client_secret`` for an OAuth connector.

        Returns an ``oauth_required`` directive (and persists the client
        credentials to every credential file for the provider) when *req*
        carries a Google ``client_id:client_secret`` pair, so the caller can
        return early instead of triggering the silent background OAuth flow.
        Returns ``None`` when there is no such pair (the caller then falls
        through to the normal ``handle_callback`` / token path).

        Raises ``HTTPException(400)`` when the pair is present but malformed or
        the connector has no OAuth provider — per the silent-failure discipline
        in REVIEW.md, a bad credential surfaces an actionable error rather than
        a perpetual ``pending`` state.
        """
        from openjarvis.connectors.oauth import (
            get_provider_for_connector,
            save_client_credentials,
        )

        raw = (req.code or req.token or "").strip()
        provider = get_provider_for_connector(connector_id)

        # Only the client-registration pair routes through the server flow;
        # a raw access token is handled by the connector's handle_callback
        # unchanged. Google's client IDs have a distinctive suffix, so a
        # colon-containing string is only treated as a Google credential
        # pair when it matches that format -- otherwise some other raw
        # token that happens to contain a colon could be misidentified.
        # Non-Google providers (Spotify, Strava, ...) have no such
        # ambiguity: every non-Google OAuth connector only ever expects a
        # client_id:client_secret pair through this path, so any
        # colon-containing string is enough to route here.
        is_google_pair = ".apps.googleusercontent.com" in raw
        is_non_google_pair = provider is not None and provider.name != "google"
        if ":" not in raw or not (is_google_pair or is_non_google_pair):
            return None

        if provider is None:
            raise HTTPException(
                status_code=400,
                detail=f"No OAuth provider configured for '{connector_id}'",
            )

        client_id, client_secret = raw.split(":", 1)
        client_id = client_id.strip()
        client_secret = client_secret.strip()
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Malformed credentials — expected 'CLIENT_ID:CLIENT_SECRET'. "
                    f"Create an OAuth client at: {provider.setup_url}"
                ),
            )

        save_client_credentials(provider, client_id, client_secret)
        # Cached instances may have resolved a stale credentials path before
        # these client creds existed; drop them so /oauth/callback rebuilds
        # them against the freshly written files.
        for cid in provider.connector_ids:
            _instances.pop(cid, None)

        return {
            "connector_id": connector_id,
            "connected": False,
            "status": "oauth_required",
            "oauth_start": f"/v1/connectors/{connector_id}/oauth/start",
            "sync_status": None,
        }

    # ------------------------------------------------------------------
    # Background-sync state tracking. Defined here (before the endpoints)
    # so that POST /connect can fire-and-forget into the same machinery
    # as POST /sync — a single source of truth for "is this connector
    # currently syncing", baseline_items, and error translation.
    # ------------------------------------------------------------------

    _sync_threads: Dict[str, Any] = {}
    _sync_cancel_events: Dict[str, threading.Event] = {}
    _sync_state: Dict[str, Dict[str, Any]] = {}
    _sync_lock = threading.Lock()
    _sync_generations: Dict[str, int] = {}
    # Connector lifecycle mutations are rare and touch shared credential,
    # instance, checkpoint, and source-ownership state. Serializing them
    # globally keeps connect/disconnect/manual-sync decisions atomic,
    # including ownership checks for sources shared by multiple connectors.
    _lifecycle_lock = threading.RLock()

    def _disconnect_pending(connector_id: str) -> bool:
        """Whether a prior disconnect is waiting for its worker to stop."""
        with _sync_lock:
            cancel_event = _sync_cancel_events.get(connector_id)
            return (
                connector_id in _sync_threads
                and cancel_event is not None
                and cancel_event.is_set()
            )

    def _reject_pending_disconnect(connector_id: str) -> None:
        """Prevent credential/source changes while an old worker still owns them."""
        if _disconnect_pending(connector_id):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Sync for '{connector_id}' is still stopping; "
                    "retry disconnect before reconnecting or syncing"
                ),
            )

    def _serialized_async(func):
        @wraps(func)
        async def wrapped(*args, **kwargs):
            with _lifecycle_lock:
                return await func(*args, **kwargs)

        return wrapped

    def _serialized_sync(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            with _lifecycle_lock:
                return func(*args, **kwargs)

        return wrapped

    def _publish_sync_state(
        connector_id: str,
        generation: int,
        state: Dict[str, Any],
    ) -> bool:
        """Publish worker state only while it still owns this lifecycle."""
        with _sync_lock:
            if _sync_generations.get(connector_id, 0) != generation:
                return False
            _sync_state[connector_id] = state
            return True

    def _translate_sync_error(raw: str) -> str:
        """Map common backend exceptions to a short user-facing message."""
        if "401" in raw or "Unauthorized" in raw:
            return "Authentication failed — credentials may have expired."
        if "403" in raw or "Forbidden" in raw:
            return "Permission denied — check API scopes."
        if "429" in raw or "Too Many Requests" in raw:
            return "Rate limited — wait a minute and try again."
        if "timeout" in raw.lower():
            return "Connection timed out."
        return raw

    @_serialized_sync
    def _start_sync(connector_id: str, instance: Any) -> str:
        """Spawn a background sync; returns ``"started"`` or ``"already_syncing"``.

        Records baseline items in ``_sync_state`` so GET /{id}/sync polls
        can compute "new this run" deltas, and translates exceptions into
        the same compact error strings the POST /sync handler used to do
        inline. Both POST /connect (auto-ingest) and POST /sync (manual)
        route through here so they share guard, state, and error handling.
        """
        with _sync_lock:
            existing = _sync_threads.get(connector_id)
            if existing and existing.is_alive():
                return "already_syncing"
            # Detect a disconnect that completes while the checkpoint baseline
            # below is being read, before this start has published its thread.
            # Without a generation token that race can launch a writer after
            # disconnect has already purged the connector's indexed content.
            start_generation = _sync_generations.get(connector_id, 0)

        # Snapshot the prior checkpoint count so the GET handler can
        # report "X new this run" without each client tracking it.
        baseline_items = 0
        try:
            from openjarvis.connectors.pipeline import IngestionPipeline
            from openjarvis.connectors.store import KnowledgeStore
            from openjarvis.connectors.sync_engine import SyncEngine

            with KnowledgeStore() as store:
                with SyncEngine(
                    pipeline=IngestionPipeline(store=store),
                ) as engine:
                    cp = engine.get_checkpoint(connector_id)
            if cp and cp.get("items_synced") is not None:
                baseline_items = int(cp["items_synced"])
        except Exception:  # noqa: BLE001
            baseline_items = 0

        cancel_event = threading.Event()

        def _run_sync() -> None:
            try:
                from openjarvis.connectors.pipeline import IngestionPipeline
                from openjarvis.connectors.store import KnowledgeStore
                from openjarvis.connectors.sync_engine import SyncEngine

                with KnowledgeStore() as store:
                    with SyncEngine(
                        pipeline=IngestionPipeline(store=store),
                    ) as engine:
                        engine.sync(instance, cancel_event=cancel_event)
                final_state = "cancelled" if cancel_event.is_set() else "complete"
                logger.info("Sync %s for %s", final_state, connector_id)
                _publish_sync_state(
                    connector_id,
                    start_generation,
                    {
                        "state": final_state,
                        "error": None,
                        "baseline_items": baseline_items,
                    },
                )
            except Exception as exc:
                if cancel_event.is_set():
                    _publish_sync_state(
                        connector_id,
                        start_generation,
                        {
                            "state": "cancelled",
                            "error": None,
                            "baseline_items": baseline_items,
                        },
                    )
                    return
                error_msg = _translate_sync_error(str(exc))
                logger.error("Sync failed for %s: %s", connector_id, error_msg)
                _publish_sync_state(
                    connector_id,
                    start_generation,
                    {
                        "state": "error",
                        "error": error_msg,
                        "baseline_items": baseline_items,
                    },
                )

        t = threading.Thread(target=_run_sync, daemon=True)
        with _sync_lock:
            if _sync_generations.get(connector_id, 0) != start_generation:
                return "cancelled"
            existing = _sync_threads.get(connector_id)
            if existing and existing.is_alive():
                return "already_syncing"
            _sync_state[connector_id] = {
                "state": "syncing",
                "error": None,
                "baseline_items": baseline_items,
            }
            _sync_cancel_events[connector_id] = cancel_event
            _sync_threads[connector_id] = t
            t.start()
        return "started"

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @router.get("")
    async def list_connectors():
        """List all registered connectors with their connection status."""
        _ensure_connectors_registered()
        results = []
        for key in sorted(ConnectorRegistry.keys()):
            try:
                instance = _get_or_create(key)
                results.append(_connector_summary(key, instance))
            except Exception:
                results.append(
                    {
                        "connector_id": key,
                        "display_name": key,
                        "auth_type": "unknown",
                        "connected": False,
                    }
                )
        return {"connectors": results}

    @router.get("/{connector_id}")
    async def connector_detail(connector_id: str):
        """Return detail for a single connector."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        instance = _get_or_create(connector_id)

        # Try to get an OAuth URL if applicable; ignore errors for non-OAuth
        # connectors.
        auth_url: Optional[str] = None
        try:
            auth_url = instance.auth_url()
        except (NotImplementedError, Exception):
            pass

        # Serialise MCP tool names only (ToolSpec objects are not JSON-safe).
        mcp_tools = []
        try:
            mcp_tools = [t.name for t in instance.mcp_tools()]
        except Exception:
            pass

        # Include OAuth provider setup info if applicable
        oauth_setup = None
        try:
            from openjarvis.connectors.oauth import (
                get_client_credentials,
                get_provider_for_connector,
            )

            provider = get_provider_for_connector(connector_id)
            if provider:
                has_creds = get_client_credentials(provider) is not None
                oauth_setup = {
                    "provider": provider.name,
                    "setup_url": provider.setup_url,
                    "setup_hint": provider.setup_hint,
                    "has_credentials": has_creds,
                }
        except Exception:
            pass

        return {
            "connector_id": connector_id,
            "display_name": getattr(instance, "display_name", connector_id),
            "auth_type": getattr(instance, "auth_type", "unknown"),
            "connected": instance.is_connected(),
            "auth_url": auth_url,
            "mcp_tools": mcp_tools,
            "oauth_setup": oauth_setup,
        }

    @router.post("/{connector_id}/connect")
    @_serialized_async
    async def connect_connector(connector_id: str, req: ConnectRequest):
        """Connect a connector using the supplied credentials."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        _reject_pending_disconnect(connector_id)
        instance = _get_or_create(connector_id)

        try:
            auth_type = getattr(instance, "auth_type", "unknown")

            if auth_type == "filesystem":
                # Filesystem connectors accept a vault / directory path.
                if req.path:
                    instance._vault_path = req.path
                    from pathlib import Path

                    instance._connected = Path(req.path).is_dir()

            elif auth_type == "oauth":
                # A pasted ``client_id:client_secret`` pair is NOT a completed
                # OAuth credential — it is the app registration. Persist it and
                # hand the UI a directive to run the in-process browser consent
                # flow (/oauth/start → /oauth/callback), which is the only path
                # that actually exchanges a code for an access_token. Previously
                # this routed into the connector's handle_callback, which spawned
                # a daemon thread that popped a browser + ran its own
                # localhost:8789 callback server; that thread fails silently in
                # the bundled desktop context, so the connector never became
                # connected and never appeared in Data Sources (issue #512).
                directive = _maybe_oauth_client_pair(connector_id, req)
                if directive is not None:
                    return directive
                if (
                    req.email
                    and req.password
                    and hasattr(instance, "connect_with_credentials")
                ):
                    from starlette.concurrency import run_in_threadpool

                    connection_options: Dict[str, Any] = {}
                    # Only the generic IMAP connector accepts a user-selected
                    # network endpoint. Its connector implementation applies
                    # the server-side public-address policy and DNS pinning.
                    if connector_id == "imap":
                        connection_options = {
                            "imap_host": req.host or "",
                            "imap_port": req.port,
                            "imap_security": req.security or "",
                        }
                    await run_in_threadpool(
                        instance.connect_with_credentials,
                        req.email,
                        req.password,
                        **connection_options,
                    )
                elif req.code:
                    from starlette.concurrency import run_in_threadpool

                    await run_in_threadpool(instance.handle_callback, req.code)
                elif req.token:
                    # A credential pasted into the ``token`` field. Connectors
                    # that accept a pre-existing access token expose ``_token``
                    # and set it directly (their real OAuth code-exchange runs
                    # via /oauth/start → /oauth/callback). Connectors that
                    # persist a manually-supplied credential — the Slack user
                    # token and the Granola API key — validate inside
                    # handle_callback, so route through it to guarantee the
                    # credential is verified before anything touches disk. A
                    # failed validation raises and is turned into HTTP 400
                    # below, leaving any existing credential intact.
                    if hasattr(instance, "_token"):
                        instance._token = req.token
                    else:
                        instance.handle_callback(req.token)

            elif connector_id in {"github_notifications", "oura"}:
                if not req.token:
                    raise HTTPException(status_code=400, detail="A token is required")
                # These token connectors persist their credentials themselves;
                # they intentionally do not expose the OAuth-only ``_token``
                # attribute or ``handle_callback`` hook.
                instance.set_token(req.token)

            elif connector_id == "weather":
                if not req.token:
                    raise HTTPException(
                        status_code=400, detail="An OpenWeather API key is required"
                    )
                location = (req.config or {}).get("location")
                if not isinstance(location, str) or not location.strip():
                    raise HTTPException(
                        status_code=400, detail="A weather location is required"
                    )
                instance.configure(api_key=req.token, location=location)

            elif connector_id == "news_rss":
                feeds = (req.config or {}).get("feeds")
                if not isinstance(feeds, list):
                    raise HTTPException(
                        status_code=400, detail="At least one RSS feed URL is required"
                    )
                instance.configure(feeds)

            else:
                # Generic: try to store token or credentials if the instance
                # exposes the relevant attributes.
                if req.token and hasattr(instance, "_token"):
                    instance._token = req.token
                if req.email and hasattr(instance, "_email"):
                    instance._email = req.email
                if req.password and hasattr(instance, "_password"):
                    instance._password = req.password

        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Auto-trigger a full backfill on a successful connect. Routed
        # through the same _start_sync helper that POST /sync uses so the
        # connection's progress is visible to GET /{id}/sync polling
        # immediately — the user shouldn't have to click "Sync Now".
        sync_status: Optional[str] = None
        if instance.is_connected():
            sync_status = _start_sync(connector_id, instance)

        return {
            "connector_id": connector_id,
            "connected": instance.is_connected(),
            "status": "connected" if instance.is_connected() else "pending",
            "sync_status": sync_status,
        }

    @router.post("/{connector_id}/disconnect")
    @_serialized_async
    async def disconnect_connector(connector_id: str):
        """Disconnect a connector and clear its credentials."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        instance = _get_or_create(connector_id)
        with _sync_lock:
            _sync_generations[connector_id] = _sync_generations.get(connector_id, 0) + 1
            cancel_event = _sync_cancel_events.get(connector_id)
            sync_thread = _sync_threads.get(connector_id)
            if cancel_event is not None:
                cancel_event.set()
            if sync_thread is not None and sync_thread.is_alive():
                previous_state = _sync_state.get(connector_id, {})
                _sync_state[connector_id] = {
                    **previous_state,
                    "state": "stopping",
                    "error": None,
                }

        if sync_thread is not None and sync_thread.is_alive():
            sync_thread.join(timeout=_SYNC_STOP_TIMEOUT_SECONDS)
        if sync_thread is not None and sync_thread.is_alive():
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Sync for '{connector_id}' is still stopping; "
                    "indexed content was not purged"
                ),
            )

        # Only revoke/delete credentials after the worker has relinquished
        # the old connection.  A timeout must leave the connector usable and
        # reject reconnect attempts, rather than silently switching source
        # state underneath a still-running writer.
        try:
            instance.disconnect()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        # A source can be shared by multiple connector implementations
        # (Gmail OAuth and Gmail IMAP both write source='gmail'). Preserve it
        # while another owner is connected; otherwise purge it only after the
        # in-flight writer has stopped.
        purge_sources = set(_knowledge_sources(connector_id, instance))
        for other_id in ConnectorRegistry.keys():
            if other_id == connector_id:
                continue
            other_cls = ConnectorRegistry.get(other_id)
            shared = purge_sources.intersection(_knowledge_sources(other_id, other_cls))
            if not shared:
                continue
            try:
                if _get_or_create(other_id).is_connected():
                    purge_sources.difference_update(shared)
            except Exception:
                # If ownership cannot be established safely, retain data.
                purge_sources.difference_update(shared)

        try:
            from openjarvis.connectors.pipeline import IngestionPipeline
            from openjarvis.connectors.store import KnowledgeStore
            from openjarvis.connectors.sync_engine import SyncEngine

            with KnowledgeStore() as store:
                with SyncEngine(
                    pipeline=IngestionPipeline(store=store),
                ) as engine:
                    old_checkpoint = engine.get_checkpoint(connector_id)
                    engine.reset_checkpoint(connector_id)
                    try:
                        store.delete_by_sources(purge_sources)
                    except Exception:
                        engine.restore_checkpoint(connector_id, old_checkpoint)
                        raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Disconnect cleanup failed for %s", connector_id)
            raise HTTPException(
                status_code=500,
                detail=f"Disconnected, but indexed-data cleanup failed: {exc}",
            )

        with _sync_lock:
            _sync_cancel_events.pop(connector_id, None)
            _sync_threads.pop(connector_id, None)
            _sync_state.pop(connector_id, None)

        return {
            "connector_id": connector_id,
            "connected": False,
            "status": "disconnected",
        }

    @router.get("/{connector_id}/oauth/start")
    async def oauth_start(connector_id: str, request: Request):
        """Redirect to the OAuth provider's consent page.

        The callback will come back to /v1/connectors/{id}/oauth/callback.
        """
        from urllib.parse import urlencode

        from openjarvis.connectors.oauth import (
            get_client_credentials,
            get_provider_for_connector,
        )

        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(404, f"Connector '{connector_id}' not found")

        provider = get_provider_for_connector(connector_id)
        if not provider:
            raise HTTPException(400, f"No OAuth provider for '{connector_id}'")

        creds = get_client_credentials(provider)
        if not creds:
            raise HTTPException(
                400,
                f"No client credentials configured for {provider.display_name}. "
                f"Set up at: {provider.setup_url}",
            )

        client_id, _ = creds
        # Build callback URL pointing to our own server
        base_url = str(request.base_url).rstrip("/")
        callback_url = f"{base_url}/v1/connectors/{connector_id}/oauth/callback"

        params = {
            "client_id": client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": " ".join(provider.scopes),
            **provider.extra_auth_params,
        }
        auth_url = f"{provider.auth_endpoint}?{urlencode(params)}"

        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=auth_url)

    @router.get("/{connector_id}/oauth/callback")
    @_serialized_async
    async def oauth_callback(
        connector_id: str,
        request: Request,
        code: str = "",
        error: str = "",
    ):
        """Handle OAuth callback from the provider."""
        from fastapi.responses import HTMLResponse

        from openjarvis.connectors.oauth import (
            _CONNECTORS_DIR,
            _exchange_token,
            get_client_credentials,
            get_provider_for_connector,
            require_access_token,
            save_tokens,
        )

        _ensure_connectors_registered()

        _reject_pending_disconnect(connector_id)

        if error:
            _style = "font-family:system-ui;text-align:center;padding:60px"
            return HTMLResponse(
                content=(
                    f"<html><body style='{_style}'>"
                    f"<h2 style='color:#ef4444'>Authorization Failed</h2>"
                    f"<p>{error}</p>"
                    "<script>setTimeout(()=>window.close(),3000)</script>"
                    "</body></html>"
                ),
                status_code=400,
            )

        if not code:
            raise HTTPException(400, "Missing authorization code")

        provider = get_provider_for_connector(connector_id)
        if not provider:
            raise HTTPException(400, f"No OAuth provider for '{connector_id}'")

        creds = get_client_credentials(provider)
        if not creds:
            raise HTTPException(400, "No client credentials configured")

        client_id, client_secret = creds
        base_url = str(request.base_url).rstrip("/")
        redirect_uri = f"{base_url}/v1/connectors/{connector_id}/oauth/callback"

        try:
            tokens = _exchange_token(
                provider, code, client_id, client_secret, redirect_uri
            )
            access_token = require_access_token(tokens)
        except Exception as exc:
            _style = "font-family:system-ui;text-align:center;padding:60px"
            return HTMLResponse(
                content=(
                    f"<html><body style='{_style}'>"
                    f"<h2 style='color:#ef4444'>Token Exchange Failed</h2>"
                    f"<p>{exc}</p>"
                    "</body></html>"
                ),
                status_code=500,
            )

        payload = {
            "access_token": access_token,
            "refresh_token": tokens.get("refresh_token", ""),
            "token_type": tokens.get("token_type", "Bearer"),
            "expires_in": tokens.get("expires_in", 3600),
            "client_id": client_id,
            "client_secret": client_secret,
        }

        for filename in provider.credential_files:
            save_tokens(str(_CONNECTORS_DIR / filename), payload)

        # Clear cached instance so it picks up new credentials
        _instances.pop(connector_id, None)

        _style = "font-family:system-ui;text-align:center;padding:60px"
        return HTMLResponse(
            content=(
                f"<html><body style='{_style}'>"
                "<h2 style='color:#22c55e'>Connected!</h2>"
                "<p>You can close this tab and return to OpenJarvis.</p>"
                "<script>setTimeout(()=>window.close(),2000)</script>"
                "</body></html>"
            )
        )

    @router.post("/{connector_id}/sync")
    @_serialized_sync
    def trigger_sync(connector_id: str) -> Dict[str, Any]:
        """Trigger a sync in the background and return immediately."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        inst = _get_or_create(connector_id)
        _reject_pending_disconnect(connector_id)
        if not inst.is_connected():
            raise HTTPException(
                status_code=400,
                detail=f"Connector '{connector_id}' is not connected",
            )
        status = _start_sync(connector_id, inst)
        return {"connector_id": connector_id, "status": status}

    @router.get("/{connector_id}/sync")
    async def sync_status(connector_id: str):
        """Return the current sync status for a connector."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        instance = _get_or_create(connector_id)
        try:
            status = instance.sync_status()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        # Override with router-level sync state (background thread tracking)
        bg = _sync_state.get(connector_id, {})
        bg_thread = _sync_threads.get(connector_id)
        is_bg_running = bg_thread is not None and bg_thread.is_alive()

        # Fall back to the SyncEngine's persistent checkpoint for items_synced
        # and last_sync. The connector's own sync_status() only reflects state
        # accumulated since the current connector instance was created, so a
        # fresh process / fresh `_get_or_create` flips back to zeros even when
        # tens of thousands of items have already been ingested historically.
        # The checkpoint table is the source of truth.
        checkpoint: Optional[Dict[str, Any]] = None
        oldest_item_date: Optional[str] = None
        try:
            from openjarvis.connectors.pipeline import IngestionPipeline
            from openjarvis.connectors.store import KnowledgeStore
            from openjarvis.connectors.sync_engine import SyncEngine

            with KnowledgeStore() as store:
                with SyncEngine(
                    pipeline=IngestionPipeline(store=store),
                ) as engine:
                    checkpoint = engine.get_checkpoint(connector_id)

                sources = _knowledge_sources(connector_id, instance)
                placeholders = ", ".join("?" for _ in sources)
                row = store._conn.execute(
                    "SELECT MIN(timestamp) FROM knowledge_chunks "
                    f"WHERE source IN ({placeholders}) AND timestamp != '' "
                    "AND deleted_at IS NULL",
                    sources,
                ).fetchone()
                if row is not None and row[0]:
                    oldest_item_date = str(row[0])
        except Exception:  # noqa: BLE001
            checkpoint = None

        # Prefer the checkpoint's items_synced — it is the running cumulative
        # total across every sync this connector has ever run. The connector
        # instance's own counter only tracks what *this* in-memory run has
        # processed, so after a fresh sync of 30 new emails the connector
        # reports 30 while the checkpoint reflects the correct 8,626 total.
        if checkpoint and checkpoint.get("items_synced") is not None:
            items_synced = int(checkpoint["items_synced"])
        else:
            items_synced = status.items_synced
        # items_total reflects the connector's currently-known target for
        # this sync run (e.g. number of IMAP message IDs matched). Leave it
        # at 0 when unknown — the UI uses items_synced >= items_total > 0 as
        # the "complete inbox" signal, which would spuriously fire on every
        # page load if we masked the zero with items_synced as a fallback.
        items_total = status.items_total
        last_sync_str: Optional[str]
        if status.last_sync:
            last_sync_str = status.last_sync.isoformat()
        elif checkpoint and checkpoint.get("last_sync"):
            last_sync_str = checkpoint["last_sync"]
        else:
            last_sync_str = None

        # Determine effective state
        if _disconnect_pending(connector_id):
            effective_state = "stopping"
        elif is_bg_running:
            effective_state = "syncing"
        elif bg.get("state") == "error":
            effective_state = "error"
        elif status.state != "idle":
            effective_state = status.state
        else:
            effective_state = status.state

        # Use the bg error if the connector doesn't have one
        effective_error = (
            status.error or bg.get("error") or (checkpoint or {}).get("error")
        )

        # Items processed during the *current* (or just-finished) run = total
        # minus the baseline captured when this sync was kicked off. This
        # lets the UI surface "30 new emails (8,623 total indexed)" without
        # the client having to track its own baseline.
        baseline_items = bg.get("baseline_items")
        new_items_synced: Optional[int] = None
        if isinstance(baseline_items, int):
            new_items_synced = max(0, items_synced - baseline_items)

        return {
            "connector_id": connector_id,
            "state": effective_state,
            "items_synced": items_synced,
            "items_total": items_total,
            "new_items_synced": new_items_synced,
            "last_sync": last_sync_str,
            "oldest_item_date": oldest_item_date,
            "error": effective_error,
        }

    return router


__all__ = ["ConnectRequest", "create_connectors_router"]
