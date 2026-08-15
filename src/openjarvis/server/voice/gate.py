"""Release gate for Chat Web voice: is the Gemini Live path available?"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request

GEMINI_LIVE_POC_ENABLED_ENV = "OPENJARVIS_GEMINI_LIVE_POC_ENABLED"
GEMINI_LIVE_ALLOWLIST_ENV = "OPENJARVIS_GEMINI_LIVE_ALLOWLIST"
GEMINI_LIVE_MODEL_ENV = "OPENJARVIS_GEMINI_LIVE_MODEL"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
DEFAULT_GEMINI_LIVE_MODEL = "gemini-3.1-flash-live-preview"

router = APIRouter(tags=["voice-release-gate"])


def gemini_live_poc_available(
    user_id: str | None,
    *,
    loopback_development: bool = False,
) -> tuple[bool, str | None]:
    if loopback_development:
        if not os.environ.get(GEMINI_API_KEY_ENV, "").strip():
            return False, "gemini_api_key_missing"
        return True, None
    if os.environ.get(GEMINI_LIVE_POC_ENABLED_ENV, "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        return False, "poc_disabled"
    if not user_id:
        return False, "poc_unauthenticated"
    allowlist = {
        entry.strip()
        for entry in os.environ.get(GEMINI_LIVE_ALLOWLIST_ENV, "").split(",")
        if entry.strip()
    }
    if not allowlist:
        return False, "poc_allowlist_missing"
    if user_id not in allowlist:
        return False, "poc_user_not_allowlisted"
    if not os.environ.get(GEMINI_API_KEY_ENV, "").strip():
        return False, "gemini_api_key_missing"
    return True, None


@router.get("/api/voice/availability")
def voice_availability(request: Request) -> dict[str, bool | str | None]:
    """Report whether voice can start.

    This router mounts unconditionally while the voice router mounts only
    under ``gemini_live_poc_enabled`` — so this endpoint answers even when
    voice is off, which is how the UI explains *why* it is off. Do not fold
    the two routers together.
    """
    return {
        "gemini_live_enabled": bool(
            getattr(request.app.state, "gemini_live_poc_enabled", False)
        ),
        "gemini_live_reason": getattr(
            request.app.state,
            "gemini_live_poc_unavailable_reason",
            "poc_disabled",
        ),
    }


__all__ = [
    "DEFAULT_GEMINI_LIVE_MODEL",
    "GEMINI_API_KEY_ENV",
    "GEMINI_LIVE_ALLOWLIST_ENV",
    "GEMINI_LIVE_MODEL_ENV",
    "GEMINI_LIVE_POC_ENABLED_ENV",
    "gemini_live_poc_available",
    "router",
]
