"""Small router exposing the anonymous analytics identity to the frontend.

The Tauri desktop app and web frontend need the same ``anon_id`` that
the backend and install.sh use so that all events tie to one person.
This endpoint returns that ID (generating it on first call) plus the
public PostHog project key and host so the frontend can initialise
``posthog-js`` against the same project.

Uses the server's normal API-key authentication when configured.
The returned project key is a public PostHog token, not a secret.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

import tomlkit
from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from openjarvis.analytics.bridge import EventBridge
from openjarvis.analytics.client import AnalyticsClient
from openjarvis.analytics.identity import (
    get_or_create_anon_id,
    is_analytics_enabled,
)
from openjarvis.core.config import JarvisConfig, load_config

logger = logging.getLogger(__name__)
_preference_lock = threading.RLock()


class AnalyticsIdentity(BaseModel):
    enabled: bool
    anon_id: str
    host: str
    key: str
    choice_recorded: bool = False


class AnalyticsPreference(BaseModel):
    """Only the analytics choice belongs here; contest details go elsewhere."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


@router.get("/identity", response_model=AnalyticsIdentity)
def get_identity(request: Request) -> AnalyticsIdentity:
    """Return the analytics identity for the current install.

    If analytics is disabled in config, still return a
    structurally valid response with ``enabled=False`` so the frontend
    can decide what to do; never throw.
    """
    cfg = getattr(request.app.state, "config", None) or load_config()
    enabled = is_analytics_enabled(cfg.analytics)
    anon_id = get_or_create_anon_id(cfg.analytics.anon_id_path) if enabled else ""
    return AnalyticsIdentity(
        enabled=enabled,
        anon_id=anon_id,
        host=cfg.analytics.host,
        key=cfg.analytics.key if enabled else "",
        choice_recorded=cfg.analytics.choice_recorded,
    )


def stop_analytics(app: FastAPI, *, wait: bool = True) -> None:
    """Detach the event bridge and close the current analytics client."""
    bridge = getattr(app.state, "analytics_bridge", None)
    client = getattr(app.state, "analytics_client", None)
    app.state.analytics_bridge = None
    app.state.analytics_client = None
    if client is not None and not wait:
        client.disable()
    if bridge is not None:
        try:
            bridge.stop()
        except Exception:
            logger.debug("Analytics bridge shutdown failed", exc_info=True)
    if client is not None:
        client.shutdown(wait=wait)


def configure_analytics(app: FastAPI, cfg: JarvisConfig) -> None:
    """Apply a sharing choice immediately to this running server."""
    stop_analytics(app, wait=False)
    app.state.config = cfg
    if not is_analytics_enabled(cfg.analytics):
        return
    client = AnalyticsClient(cfg.analytics)
    app.state.analytics_client = client
    bus = getattr(app.state, "bus", None)
    if bus is not None and client.enabled:
        bridge = EventBridge(bus, client)
        app.state.analytics_bridge = bridge
        bridge.start()


@router.post("/preference", response_model=AnalyticsIdentity)
def set_preference(choice: AnalyticsPreference, request: Request) -> AnalyticsIdentity:
    """Persist an explicit UI choice and update analytics without restarting."""
    with _preference_lock:
        cfg = getattr(request.app.state, "config", None) or load_config()
        path = cfg._config_path
        temporary: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            doc = (
                tomlkit.parse(path.read_text(encoding="utf-8"))
                if path.exists()
                else tomlkit.document()
            )
            if "analytics" not in doc:
                doc.add("analytics", tomlkit.table())
            doc["analytics"]["enabled"] = choice.enabled
            doc["analytics"]["choice_recorded"] = True
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(tomlkit.dumps(doc))
            temporary.replace(path)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not save analytics preference: %s", exc)
            raise HTTPException(
                status_code=500, detail="Could not save your analytics choice."
            ) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        cfg.analytics.enabled = choice.enabled
        cfg.analytics.choice_recorded = True
        load_config.cache_clear()
        client = getattr(request.app.state, "analytics_client", None)
        if (choice.enabled and (client is None or not client.enabled)) or (
            not choice.enabled and client is not None
        ):
            configure_analytics(request.app, cfg)
        else:
            request.app.state.config = cfg
        return get_identity(request)


__all__ = ["configure_analytics", "router", "stop_analytics"]
