"""FastAPI route for kiosk frontend callbacks."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class KioskRespondRequest(BaseModel):
    accept: bool


@router.post("/api/kiosk/respond")
async def kiosk_respond(body: KioskRespondRequest, request: Request):
    """Frontend calls this when the user taps Yes/No on the consent popup.

    Request body: ``{"accept": true}`` or ``{"accept": false}``.
    """
    from openjarvis.kiosk.runtime import push_user_response

    response = "accept" if body.accept else "decline"
    await push_user_response(response)
    return {"ok": True}


@router.get("/api/kiosk/state")
async def kiosk_state(request: Request):
    """Debug: return whether kiosk is running."""
    running = getattr(request.app.state, "kiosk_running", False)
    return {"ok": True, "running": running}
