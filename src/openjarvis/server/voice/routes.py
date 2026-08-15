"""Serve one Pipecat Voice session over WebRTC."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from openjarvis.server.voice.llm import message_text
from openjarvis.server.voice.persistence import session_store_for
from openjarvis.server.voice.pipeline import (
    VoiceLeaseBusy,
    build_voice_pipeline,
    claim_voice_lease,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pipecat-voice"])

# How much of a context has already reached the Chat thread, as
# (messages_consumed, last_turn_id). Kept on the context itself so a teardown
# that fires twice cannot write the conversation twice.
_SAVED_ATTR = "_openjarvis_saved_upto"


def save_voice_conversation(
    sessions: Any, *, voice_session_id: str, chat_thread_id: str, context: Any
) -> int:
    """Write what was said to the Chat thread, in one pass at the end.

    There is no mid-session write. The old runtime recorded prompts as they
    arrived but answers only after full playback, so every interrupted answer
    was dropped and the model learned to imitate the short ones that survived.

    Returns the number of turns written.
    """
    messages = list(context.get_messages())
    consumed, turn_id = getattr(context, _SAVED_ATTR, (0, 0))
    saved = 0

    for message in messages[consumed:]:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = message_text(message).strip()
        if not content:
            continue
        turn_id += 1
        try:
            sessions.record_final_turn(
                voice_session_id=voice_session_id,
                chat_thread_id=chat_thread_id,
                turn_id=turn_id,
                role=role,
                content=content,
            )
        except Exception:
            # One rejected turn must not cost the user the rest of the
            # conversation.
            logger.warning("voice turn %s could not be saved", turn_id, exc_info=True)
            continue
        saved += 1

    setattr(context, _SAVED_ATTR, (len(messages), turn_id))
    return saved


def persist_voice_session(
    store: Any,
    sessions: Any,
    *,
    voice_session_id: str,
    chat_thread_id: str,
) -> int:
    """Write a finished Voice conversation to the SQLite session store.

    Reads the turns ``save_voice_conversation`` has already recorded, so that
    function keeps its signature and its two existing tests.

    Synchronous on purpose: the caller hands the whole function to
    ``asyncio.to_thread`` once, so a session costs one hand-off rather than one
    per turn. ``sqlite3`` blocks and must not run on the event loop.

    The chat thread is the identity. ``SessionStore`` is keyed per user, but
    the sidebar shows one conversation at a time, so ``voice:{thread}`` narrows
    it to a conversation. ``KioskPage.tsx:68`` creates a fresh thread on every
    voice start, so the key is never reused and the write stays append-only.

    Returns the number of messages written; 0 when there is no store.
    """
    if store is None:
        return 0
    try:
        turns = sessions.get_session(voice_session_id).turns
        ordered = sorted(
            turns.values(), key=lambda turn: (turn.created_at, turn.turn_id)
        )
    except Exception:
        # end_session may already have dropped it, or a turn may be malformed.
        # Teardown must not raise: an exception here would strand the Voice
        # lease and refuse every later session until the server restarts.
        logger.warning("voice session gone before persistence", exc_info=True)
        return 0
    if not ordered:
        return 0

    try:
        session = store.get_or_create(f"voice:{chat_thread_id}", channel="voice")
    except Exception:
        logger.warning(
            "voice session could not be opened for persistence", exc_info=True
        )
        return 0

    written = 0
    for turn in ordered:
        try:
            store.save_message(
                session.session_id, turn.role, turn.content, channel="voice"
            )
        except Exception:
            # Durability is an addition, not a precondition. The RAM dict and
            # the browser still hold the conversation.
            logger.warning("voice turn could not be persisted", exc_info=True)
            continue
        written += 1
    return written


class VoiceOfferData(BaseModel):
    """What the client asks for, carried inside the WebRTC offer."""

    chat_thread_id: str = ""
    model: str = ""


class WebRTCOfferRequest(BaseModel):
    """The SDP offer a Pipecat JavaScript client sends to open a session.

    Shaped after pipecat's own ``SmallWebRTCRequest``: everything specific to
    this application travels in ``requestData``, which is the field the
    JavaScript transport sends it in.
    """

    sdp: str
    type: str
    pc_id: str | None = None
    restart_pc: bool | None = None
    requestData: VoiceOfferData = VoiceOfferData()  # noqa: N815 - the client's field name


_RENDERER: Any = None


async def _renderer() -> Any:
    """The one local VieNeu renderer every session speaks through.

    Built once and kept warm. ``VieNeuRealtimeTts`` caches its ONNX runtime per
    instance, so building one per session paid the model load inside the first
    synthesis: measured at 3.18 s to the first chunk and a 0.32x realtime
    factor, against 0.18 s and 2.05x once warm. Below realtime means playback
    starts and then runs dry, which is why every session's opening word
    stuttered — "chào…bạn" — and why nothing after it did.

    Loading here costs the first connection of the process ~3 s before its SDP
    answer, where nothing is playing yet, instead of breaking a word in half.

    Sharing is safe: the lease admits one Voice session at a time, and the
    renderer serialises inference on its own lock.
    """
    global _RENDERER
    if _RENDERER is not None:
        return _RENDERER

    from openjarvis.server.voice.tts_engine import (
        VieNeuRealtimeTts,
        load_accepted_vieneu_artifact,
    )

    artifact_dir = os.environ.get("OPENJARVIS_LOCAL_TTS_ARTIFACT_DIR", "").strip()
    if not artifact_dir:
        raise RuntimeError("vieneu_artifact_required")
    renderer = VieNeuRealtimeTts(load_accepted_vieneu_artifact(Path(artifact_dir)))
    # Only cached once the model is up: a half-built renderer would leave Voice
    # broken until the process restarted.
    await renderer.start()
    _RENDERER = renderer
    return _RENDERER


def _transcriber() -> Any:
    """Build the Gemini Live transcriber, which local VAD drives."""
    from openjarvis.server.voice.stt import GeminiLiveTranscriptionService

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("gemini_api_key_required")
    return GeminiLiveTranscriptionService(api_key=api_key)


def _handler(request: Request) -> Any:
    """One handler per app, so a reconnect can find its peer connection."""
    from pipecat.transports.smallwebrtc.request_handler import (
        SmallWebRTCRequestHandler,
    )

    handler = getattr(request.app.state, "pipecat_webrtc_handler", None)
    if handler is None:
        handler = SmallWebRTCRequestHandler()
        request.app.state.pipecat_webrtc_handler = handler
    return handler


@router.post("/api/voice/webrtc/offer")
async def voice_webrtc_offer(body: WebRTCOfferRequest, request: Request):
    """Answer an SDP offer, or refuse so the caller falls back to text."""
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest
    from pipecat.workers.runner import WorkerRunner

    sessions = getattr(request.app.state, "voice_session_service", None)
    runtime = getattr(request.app.state, "native_agent_runtime", None)
    if sessions is None or runtime is None:
        raise HTTPException(status_code=503, detail="voice_agent_unavailable")

    model = body.requestData.model.strip() or getattr(request.app.state, "model", "")
    try:
        binding = runtime.bind(model=model)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="voice_model_unavailable") from exc

    try:
        session = claim_voice_lease(
            sessions,
            chat_thread_id=body.requestData.chat_thread_id,
            execution_binding=binding,
        )
    except VoiceLeaseBusy as busy:
        # One Voice session at a time. The client speaks to the text path.
        return JSONResponse(
            status_code=409,
            content={"status": busy.status, "fallback": busy.fallback},
        )

    from openjarvis.server.voice.runtime import _memory_recall

    # The same gate the chat path uses: config.agent.context_from_memory off
    # means no recall, and (None, None) collapses to no injection below.
    recall_backend, recall_config = _memory_recall(
        getattr(request.app.state, "memory_backend", None),
        getattr(request.app.state, "config", None),
    )
    recall = (recall_backend, recall_config) if recall_backend is not None else None

    async def run_until_disconnected(
        worker: Any, context: Any, connection: Any
    ) -> None:
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)

        # runner.run() only returns on idle timeout or cancellation; the peer
        # leaving must not hold the lease for minutes. Watch the ICE state and
        # reap the pipeline the moment it goes.
        closed = asyncio.Event()
        peer = connection.pc

        def _on_connection_state_change() -> None:
            if peer.connectionState in ("closed", "failed"):
                closed.set()

        peer.on("connectionstatechange", _on_connection_state_change)

        run_task = asyncio.create_task(runner.run())
        closed_task = asyncio.create_task(closed.wait())
        try:
            await asyncio.wait(
                {run_task, closed_task}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            closed_task.cancel()
            if not run_task.done():
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)
            save_voice_conversation(
                sessions,
                voice_session_id=session.voice_session_id,
                chat_thread_id=session.chat_thread_id,
                context=context,
            )
            # After the session is over, never between turns: the critical
            # path transcript -> agent -> TTS gains no I/O from this.
            await asyncio.to_thread(
                persist_voice_session,
                session_store_for(request.app.state),
                sessions,
                voice_session_id=session.voice_session_id,
                chat_thread_id=session.chat_thread_id,
            )
            # In the same finally as the save: a lease that outlives its
            # pipeline refuses every later session with a text fallback.
            sessions.end_session(session.voice_session_id, reason="disconnected")

    async def start_pipeline(connection: Any) -> None:
        # pipecat runs this callback inside its own try/except: a failure here
        # is logged, but the handshake still answers with a valid SDP. Without
        # this, run_until_disconnected — the only place that releases the
        # lease — is never scheduled, and the lease sits held until
        # expire_stale_sessions reclaims it 300 s later.
        try:
            worker, context = build_voice_pipeline(
                connection=connection,
                binding=session.execution_binding,
                renderer=await _renderer(),
                stt=_transcriber(),
                recall=recall,
            )
            request.app.state.pipecat_voice_context = context
            # Not awaited: the handshake must answer now, and the pipeline
            # lives for as long as the peer connection does.
            request.app.state.pipecat_voice_task = asyncio.create_task(
                run_until_disconnected(worker, context, connection)
            )
        except Exception:
            sessions.end_session(session.voice_session_id, reason="pipeline_failed")
            raise

    answer = await _handler(request).handle_web_request(
        SmallWebRTCRequest(
            sdp=body.sdp,
            type=body.type,
            pc_id=body.pc_id,
            restart_pc=body.restart_pc,
        ),
        webrtc_connection_callback=start_pipeline,
    )
    if answer is None:
        raise HTTPException(status_code=503, detail="webrtc_handshake_failed")
    return answer
