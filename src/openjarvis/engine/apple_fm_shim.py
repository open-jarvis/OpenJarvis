"""Apple Foundation Models shim.

Thin FastAPI server exposing Apple FM SDK as OpenAI-compatible API.
Only runs on macOS 26+ with Apple Silicon. Wraps apple-fm-sdk's
LanguageModelSession as /v1/chat/completions and /v1/models endpoints.

**Token counts:** The Apple FM SDK does not expose token counts. The shim
estimates usage from text length (~4 chars/token). Throughput and energy
benchmarks will reflect this approximation.

Usage:
    uvicorn openjarvis.engine.apple_fm_shim:app \
        --host 127.0.0.1 --port 8079
"""

from __future__ import annotations

import json
import platform
import sys
import time
import uuid

if platform.system() != "Darwin":
    print(
        "apple_fm_shim: only available on macOS",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import apple_fm_sdk as fm  # type: ignore[import-untyped]
except ImportError:
    print(
        "apple_fm_shim: pip install apple-fm-sdk",
        file=sys.stderr,
    )
    sys.exit(1)

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


def _estimate_tokens(text: str) -> int:
    """Approximate token count (~4 chars/token for typical LLM tokenizers)."""
    return max(1, len(text) // 4) if text else 0


def _build_prompt(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        if m.role == "system":
            parts.append(f"[System] {m.content}")
        elif m.role in ("user", "assistant"):
            parts.append(m.content)
    return "\n".join(parts)


@app.get("/health")
def health() -> JSONResponse:
    model = fm.SystemLanguageModel()
    is_available, _ = model.is_available()
    status = "ok" if is_available else "unavailable"
    code = 200 if is_available else 503
    return JSONResponse({"status": status}, status_code=code)


@app.get("/v1/models")
def list_models() -> JSONResponse:
    return JSONResponse({
        "object": "list",
        "data": [
            {"id": MODEL_ID, "object": "model", "owned_by": "apple"},
        ],
    })


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    req: ChatRequest,
) -> JSONResponse | StreamingResponse:
    prompt = _build_prompt(req.messages)
    session = fm.LanguageModelSession()

    if req.stream:
        async def generate():
            cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            async for token in session.stream_response(prompt):
                chunk = {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": MODEL_ID,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": token},
                        "finish_reason": None,
                    }],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            final = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": MODEL_ID,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(), media_type="text/event-stream",
        )

    text = await session.respond(prompt)
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    prompt_tokens = _estimate_tokens(prompt)
    completion_tokens = _estimate_tokens(text)
    return JSONResponse({
        "id": cid,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    })
