"""Nexa SDK shim.

Thin FastAPI server wrapping the Nexa SDK (``nexaai``) as an
OpenAI-compatible API on port 18181.  Intended for on-device inference
with GGUF models on Apple Silicon or CPU.

**Token counts:** The Nexa SDK does not expose token counts in responses.
The shim returns 0 for prompt/completion/total tokens. Savings and
leaderboard metrics will not include sessions that use this engine.

Usage:
    uvicorn openjarvis.engine.nexa_shim:app \
        --host 127.0.0.1 --port 18181
"""

from __future__ import annotations

import json
import sys
import time
import uuid

try:
    import nexaai  # type: ignore[import-untyped]
except ImportError:
    print(
        "nexa_shim: pip install nexaai",
        file=sys.stderr,
    )
    sys.exit(1)

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Nexa SDK Shim")

MODEL_ID = "nexa"

_llm: nexaai.LLM | None = None


def _get_llm() -> nexaai.LLM:
    global _llm
    if _llm is None:
        _llm = nexaai.LLM()
    return _llm


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


@app.get("/health")
def health() -> JSONResponse:
    try:
        _get_llm()
        return JSONResponse({"status": "ok"}, status_code=200)
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)


@app.get("/v1/models")
def list_models() -> JSONResponse:
    return JSONResponse({
        "object": "list",
        "data": [
            {"id": MODEL_ID, "object": "model", "owned_by": "nexa"},
        ],
    })


@app.post("/v1/chat/completions")
async def chat_completions(
    req: ChatRequest,
) -> JSONResponse | StreamingResponse:
    prompt = _build_prompt(req.messages)
    llm = _get_llm()

    if req.stream:
        async def generate():
            cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            for token in llm.generate(prompt, max_tokens=req.max_tokens):
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

    text = llm.generate(prompt, max_tokens=req.max_tokens)
    if isinstance(text, list):
        text = "".join(text)
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
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
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    })
