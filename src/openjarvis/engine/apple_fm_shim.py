"""Apple Foundation Models shim.

Thin FastAPI server exposing Apple Intelligence's on-device foundation
model as an OpenAI-compatible API. Only runs on macOS 26+ with Apple
Intelligence enabled. Wraps Apple's `apple-fm-sdk`'s
``LanguageModelSession`` as ``/v1/chat/completions`` and ``/v1/models``
endpoints.

**Token counts:** The Apple FM SDK does not expose token counts. The
shim returns 0 for all token counts. Throughput and energy benchmarks
will reflect this limitation.

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
        "apple_fm_shim: apple-fm-sdk is not available. The SDK is not on\n"
        "PyPI yet; clone https://github.com/apple/python-apple-fm-sdk and\n"
        "install from source:\n"
        "    git clone https://github.com/apple/python-apple-fm-sdk\n"
        "    uv pip install -e ./python-apple-fm-sdk\n"
        "Requires macOS 26+, Xcode 26+, and Apple Intelligence enabled.",
        file=sys.stderr,
    )
    sys.exit(1)

import json
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

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


def _build_prompt(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        if m.role == "system":
            parts.append(f"[System] {m.content}")
        elif m.role in ("user", "assistant"):
            parts.append(m.content)
    return "\n".join(parts)


def _generation_options(req: ChatRequest) -> apple_fm_sdk.GenerationOptions:
    """Build the per-request GenerationOptions from a ChatRequest.

    Apple FM doesn't take ``max_tokens`` / ``temperature`` as positional
    args to ``respond`` / ``stream_response`` — they live on a
    ``GenerationOptions`` object passed via the ``options`` kwarg.
    """
    return apple_fm_sdk.GenerationOptions(
        temperature=req.temperature,
        maximum_response_tokens=req.max_tokens,
    )


@app.get("/health")
def health() -> JSONResponse:
    # SystemLanguageModel.is_available() is an *instance* method that
    # returns (bool, reason | None). Unpack so we can both gate the
    # response code and surface the reason for unavailability.
    available, reason = apple_fm_sdk.SystemLanguageModel().is_available()
    if available:
        return JSONResponse({"status": "ok"}, status_code=200)
    return JSONResponse(
        {"status": "unavailable", "reason": str(reason) if reason else None},
        status_code=503,
    )


@app.get("/v1/models")
def list_models() -> JSONResponse:
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {"id": MODEL_ID, "object": "model", "owned_by": "apple"},
            ],
        }
    )


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    req: ChatRequest,
) -> JSONResponse | StreamingResponse:
    prompt = _build_prompt(req.messages)
    session = apple_fm_sdk.LanguageModelSession()
    options = _generation_options(req)

    if req.stream:

        async def generate():
            cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            # Apple FM yields cumulative snapshots, OpenAI clients expect
            # incremental deltas — diff against the last snapshot to convert
            # (see #378).
            sent = ""
            async for snapshot in session.stream_response(
                prompt,
                options=options,
            ):
                if not snapshot.startswith(sent):
                    # Snapshot diverged (model revised earlier text);
                    # fall back to resending the full snapshot.
                    delta = snapshot
                else:
                    delta = snapshot[len(sent) :]
                sent = snapshot
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
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
        )

    text = await session.respond(prompt, options=options)
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
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
    )
