"""Apple Foundation Models shim.

Thin FastAPI server exposing Apple Intelligence's on-device foundation model
as an OpenAI-compatible API, for pointing external OpenAI clients at AFM.
Only runs on macOS 26+ with Apple Intelligence enabled. Wraps
``apple-fm-sdk``'s ``LanguageModelSession`` as ``/v1/chat/completions`` and
``/v1/models``.

OpenJarvis's own preferred path is the in-process ``afm`` engine
(``openjarvis.engine.apple_fm``), which avoids an HTTP hop and a second
process whose CPU energy would otherwise land inside the same measurement
window.

Usage:
    uvicorn openjarvis.engine.apple_fm_shim:app \
        --host 127.0.0.1 --port 8079
"""

from __future__ import annotations

import platform
import sys

if platform.system() != "Darwin":
    print(
        "apple_fm_shim: only available on macOS",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import apple_fm_sdk  # type: ignore[import-untyped]
except ImportError:
    print(
        "apple_fm_shim: apple-fm-sdk is not available. Install it with:\n"
        "    DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \\\n"
        "        uv pip install 'apple-fm-sdk>=0.2.1'\n"
        "The SDK compiles Swift bindings at install time, so a full Xcode is\n"
        "required -- Command Line Tools alone fail. Requires macOS 26+ and\n"
        "Apple Intelligence enabled.",
        file=sys.stderr,
    )
    sys.exit(1)

import json
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from openjarvis.engine._apple_fm_support import SnapshotAccumulator

logger = logging.getLogger(__name__)

app = FastAPI(title="Apple FM Shim")

MODEL_ID = "apple-fm"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 1024
    stream: bool = False


def _system_language_model() -> Any:
    return apple_fm_sdk.SystemLanguageModel()


def _split_messages(messages: list[ChatMessage]) -> tuple[str, str]:
    """Split into (instructions, prompt).

    System messages become the session's ``instructions``, which is where the
    SDK wants them. Earlier versions prefixed them onto the prompt as
    ``[System] ...``, which both discards the distinction and inflates the
    prompt-token count.
    """
    system_parts = [m.content for m in messages if m.role == "system"]
    prompt_parts = [m.content for m in messages if m.role in ("user", "assistant")]
    return "\n".join(system_parts), "\n".join(prompt_parts)


def _generation_options(req: ChatRequest) -> apple_fm_sdk.GenerationOptions:
    """Build the per-request GenerationOptions from a ChatRequest.

    Apple FM doesn't take ``max_tokens`` / ``temperature`` as positional args
    to ``respond`` / ``stream_response`` -- they live on a
    ``GenerationOptions`` object passed via the ``options`` kwarg.
    """
    return apple_fm_sdk.GenerationOptions(
        temperature=req.temperature,
        maximum_response_tokens=req.max_tokens,
    )


async def _count(model: Any, value: Any) -> Optional[int]:
    """``token_count`` that degrades to ``None`` rather than failing a request."""
    try:
        return int(await model.token_count(value))
    except Exception:
        logger.debug("apple_fm_shim: token_count failed", exc_info=True)
        return None


def _usage(prompt_tokens: Optional[int], completion_tokens: Optional[int]) -> dict:
    prompt = prompt_tokens or 0
    completion = completion_tokens or 0
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _completion_tokens(
    post: Optional[int],
    prompt_tokens: Optional[int],
) -> Optional[int]:
    if post is None or prompt_tokens is None:
        return None
    return max(post - prompt_tokens, 0)


@app.get("/health")
def health() -> JSONResponse:
    # SystemLanguageModel.is_available() is an *instance* method that
    # returns (bool, reason | None). Unpack so we can both gate the
    # response code and surface the reason for unavailability.
    available, reason = _system_language_model().is_available()
    if available:
        return JSONResponse({"status": "ok"}, status_code=200)
    return JSONResponse(
        {"status": "unavailable", "reason": str(reason) if reason else None},
        status_code=503,
    )


@app.get("/v1/models")
def list_models() -> JSONResponse:
    entry: dict[str, Any] = {
        "id": MODEL_ID,
        "object": "model",
        "owned_by": "apple",
    }
    try:
        entry["context_length"] = int(_system_language_model().context_size)
    except Exception:
        logger.debug("apple_fm_shim: context_size unavailable", exc_info=True)
    return JSONResponse({"object": "list", "data": [entry]})


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    req: ChatRequest,
) -> JSONResponse | StreamingResponse:
    instructions, prompt = _split_messages(req.messages)
    model = _system_language_model()
    session = apple_fm_sdk.LanguageModelSession(
        instructions=instructions or None,
        model=model,
    )
    options = _generation_options(req)

    # Token accounting. `token_count` rejects a value and instructions
    # together, and counting instructions standalone does not match how the
    # transcript encodes them, so both ends are measured against the
    # transcript instead:
    #   prompt_tokens     = <transcript before> + <prompt alone>
    #   completion_tokens = <transcript after>  - prompt_tokens
    pre_tokens = await _count(model, session.transcript)
    prompt_only = await _count(model, prompt)
    prompt_tokens = (
        pre_tokens + prompt_only
        if pre_tokens is not None and prompt_only is not None
        else prompt_only
    )

    if req.stream:

        async def generate():
            cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            # Apple FM yields cumulative snapshots, OpenAI clients expect
            # incremental deltas (see #378). The accumulator also handles
            # guided generation revising a snapshot rather than extending it.
            accumulator = SnapshotAccumulator()
            async for snapshot in session.stream_response(
                prompt,
                options=options,
            ):
                delta = accumulator.add(snapshot)
                if not delta:
                    continue
                chunk = {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": MODEL_ID,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"

            post_tokens = await _count(model, session.transcript)
            final = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
                # Streaming clients that track cost/throughput read usage off
                # the final chunk; omitting it left them with nothing.
                "usage": _usage(
                    prompt_tokens,
                    _completion_tokens(post_tokens, prompt_tokens),
                ),
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
        )

    text = await session.respond(prompt, options=options)
    post_tokens = await _count(model, session.transcript)
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    return JSONResponse(
        {
            "id": cid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": _usage(
                prompt_tokens,
                _completion_tokens(post_tokens, prompt_tokens),
            ),
        }
    )
