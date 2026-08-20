"""Small router exposing the anonymous analytics identity to the frontend.

The Tauri desktop app and web frontend need the same ``anon_id`` that
the backend and install.sh use so that all events tie to one person.
This endpoint returns that ID (generating it on first call) plus the
public PostHog project key and host so the frontend can initialise
``posthog-js`` against the same project.

Public API — no auth required because the data returned is exactly
what the frontend would ship to PostHog anyway. The project key is
a public token, not a secret.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from openjarvis.analytics.identity import (
    get_or_create_anon_id,
    is_analytics_enabled,
)
from openjarvis.core.config import load_config


class AnalyticsIdentity(BaseModel):
    enabled: bool
    anon_id: str
    host: str
    key: str


router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


@router.get("/identity", response_model=AnalyticsIdentity)
def get_identity() -> AnalyticsIdentity:
    """Return the analytics identity for the current install.

    If analytics is disabled in config, still return a
    structurally valid response with ``enabled=False`` so the frontend
    can decide what to do; never throw.
    """
    cfg = load_config()
    enabled = is_analytics_enabled(cfg.analytics)
    anon_id = get_or_create_anon_id(cfg.analytics.anon_id_path) if enabled else ""
    return AnalyticsIdentity(
        enabled=enabled,
        anon_id=anon_id,
        host=cfg.analytics.host,
        key=cfg.analytics.key if enabled else "",
    )


__all__ = ["router"]
