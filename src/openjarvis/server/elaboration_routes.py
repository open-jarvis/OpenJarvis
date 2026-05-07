"""HTTP surface for proactive elaborations.

  GET  /v1/elaborations/stream         long-lived SSE: events `proposed`,
                                       `accepted_full`, `dismissed`
  POST /v1/elaborations/{id}/accept    marks accepted, broadcasts the full
                                       claude answer to subscribers
  POST /v1/elaborations/{id}/dismiss   marks dismissed
  GET  /v1/elaborations/{id}           current state (debug)
  GET  /v1/elaborations/recent?limit=N admin: list recent records (verifies
                                       persistence; truncates content to
                                       avoid leaking sensitive prompts)
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


@router.get("/recent")
async def list_recent_elaborations(limit: int = 10, full: bool = False) -> dict:
    """Admin endpoint: list recent elaboration records.

    Useful for verifying Postgres persistence end-to-end and for inspecting
    what the slow-Claude track has been producing. Returns records from the
    in-memory store (which is hydrated from Postgres at boot) plus a count
    of records currently held in memory.

    Query params:
      limit  — max records to return (default 10, capped at 100)
      full   — if true, include full original_question + claude_answer.
               Default false truncates them to 200 chars to avoid leaking
               prompts/answers if this endpoint isn't gated by auth.
    """
    limit = max(1, min(int(limit or 10), 100))
    store = get_store()
    # Snapshot the in-memory dict; sort by created_at desc.
    async with store._lock:  # noqa: SLF001 — admin path, single reader
        items = sorted(
            store._items.values(),  # noqa: SLF001
            key=lambda e: e.created_at,
            reverse=True,
        )[:limit]

    def _record(elab) -> dict:
        d = {
            "id": elab.id,
            "conversation_id": elab.conversation_id,
            "status": elab.status.value,
            "created_at": elab.created_at,
            "updated_at": elab.updated_at,
            "spoken_answer_len": len(elab.spoken_answer) if elab.spoken_answer else 0,
            "claude_answer_len": len(elab.claude_answer) if elab.claude_answer else 0,
            "error": elab.error,
        }
        if full:
            d["original_question"] = elab.original_question
            d["spoken_answer"] = elab.spoken_answer
            d["claude_answer"] = elab.claude_answer
        else:
            d["original_question_excerpt"] = (
                (elab.original_question or "")[:200]
            )
            d["spoken_answer_excerpt"] = (
                (elab.spoken_answer or "")[:200] if elab.spoken_answer else None
            )
            d["claude_answer_excerpt"] = (
                (elab.claude_answer or "")[:200] if elab.claude_answer else None
            )
        return d

    return {
        "in_memory_total": len(store._items),  # noqa: SLF001
        "returned": len(items),
        "records": [_record(e) for e in items],
    }


@router.get("/{elab_id}")
async def get_elaboration(elab_id: str) -> dict:
    elab = await get_store().get(elab_id)
    if elab is None:
        raise HTTPException(status_code=404, detail="elaboration not found")
    return elab.to_event_dict(include_full_answer=True)


__all__ = ["router"]
