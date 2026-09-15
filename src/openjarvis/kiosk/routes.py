"""FastAPI route for kiosk frontend callbacks."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from openjarvis.kiosk.presentation import PresentationUnavailableError

router = APIRouter()
logger = logging.getLogger(__name__)


class KioskRespondRequest(BaseModel):
    accept: bool


class EnsurePresentationRequest(BaseModel):
    display_origin: str


class ResetPresentationRequest(BaseModel):
    generation: str | None = None


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


@router.post("/api/kiosk/presentation/ensure")
async def ensure_presentation(
    body: EnsurePresentationRequest,
    request: Request,
):
    manager = getattr(request.app.state, "presentation_session_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="presentation_unavailable")
    try:
        session = await run_in_threadpool(manager.ensure, body.display_origin)
    except PresentationUnavailableError as exc:
        logger.warning("Customer display unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="presentation_unavailable"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"presentation_session_id": session.session_id}


@router.post("/api/kiosk/presentation/{session_id}/reset")
async def reset_presentation(
    session_id: str,
    request: Request,
    body: ResetPresentationRequest | None = None,
):
    manager = getattr(request.app.state, "presentation_session_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="presentation_unavailable")
    if manager.replay(session_id) is None:
        raise HTTPException(status_code=404, detail="presentation_session_not_found")
    requested_generation = body.generation if body is not None else None
    active_generation = (
        manager.active_generation(session_id)
        if hasattr(manager, "active_generation")
        else None
    )
    if requested_generation is not None and active_generation != requested_generation:
        return {"ok": True}
    voice_task = getattr(request.app.state, "pipecat_voice_task", None)
    voice_generation = getattr(request.app.state, "pipecat_voice_generation", None)
    if (
        requested_generation is not None
        and voice_generation is not None
        and voice_generation != requested_generation
    ):
        return {"ok": True}
    if isinstance(voice_task, asyncio.Future) and not voice_task.done():
        voice_task.cancel()
        await asyncio.gather(voice_task, return_exceptions=True)
    if getattr(request.app.state, "pipecat_voice_task", None) is not voice_task:
        return {"ok": True}
    if getattr(request.app.state, "pipecat_voice_generation", None) not in (
        None,
        voice_generation,
    ):
        return {"ok": True}
    if isinstance(voice_task, asyncio.Future):
        request.app.state.pipecat_voice_task = None
        request.app.state.pipecat_voice_generation = None
    generation = requested_generation or active_generation
    reset = (
        manager.reset(session_id, generation=generation)
        if generation is not None
        else manager.reset(session_id)
    )
    if not reset and manager.replay(session_id) is None:
        raise HTTPException(status_code=404, detail="presentation_session_not_found")
    return {"ok": True}
