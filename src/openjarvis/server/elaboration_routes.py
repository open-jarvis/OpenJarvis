"""HTTP surface for proactive elaborations.

  GET  /v1/elaborations/stream         long-lived SSE: events `proposed`,
                                       `accepted_full`, `dismissed`
  POST /v1/elaborations/{id}/accept    marks accepted, broadcasts the full
                                       claude answer to subscribers
  POST /v1/elaborations/{id}/dismiss   marks dismissed
  GET  /v1/elaborations/{id}           current state (debug)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from openjarvis.server.elaboration_store import get_store

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/elaborations", tags=["elaborations"])


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/stream")
async def stream_elaborations(request: Request) -> StreamingResponse:
    """Long-lived SSE channel pushing elaboration events to the frontend.

    Frontend opens this once on app boot. Heartbeat every 15s so reverse
    proxies don't kill the connection mid-pause.
    """
    store = get_store()

    async def event_gen() -> AsyncIterator[str]:
        # hello so the frontend knows the subscription is live
        yield _format_sse("ready", {"ok": True})

        sub = store.subscribe()
        sub_iter = sub.__aiter__()
        sub_task: asyncio.Task | None = None
        try:
            while True:
                if await request.is_disconnected():
                    return

                if sub_task is None or sub_task.done():
                    sub_task = asyncio.create_task(sub_iter.__anext__())

                done, _ = await asyncio.wait(
                    {sub_task},
                    timeout=15.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    yield _format_sse("heartbeat", {})
                    continue

                try:
                    ev = sub_task.result()
                except StopAsyncIteration:
                    return
                sub_task = None
                yield _format_sse(ev.event, ev.data)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Elaboration SSE error: %s", exc, exc_info=True)
            return
        finally:
            if sub_task is not None and not sub_task.done():
                sub_task.cancel()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{elab_id}/accept")
async def accept_elaboration(elab_id: str) -> dict:
    elab = await get_store().accept(elab_id)
    if elab is None:
        raise HTTPException(status_code=404, detail="elaboration not found")
    return {"status": "accepted", "id": elab.id}


@router.post("/{elab_id}/dismiss")
async def dismiss_elaboration(elab_id: str) -> dict:
    elab = await get_store().dismiss(elab_id)
    if elab is None:
        raise HTTPException(status_code=404, detail="elaboration not found")
    return {"status": "dismissed", "id": elab.id}


@router.get("/{elab_id}")
async def get_elaboration(elab_id: str) -> dict:
    elab = await get_store().get(elab_id)
    if elab is None:
        raise HTTPException(status_code=404, detail="elaboration not found")
    return elab.to_event_dict(include_full_answer=True)


__all__ = ["router"]
