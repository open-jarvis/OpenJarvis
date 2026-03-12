"""Nexa SDK shim.

Thin FastAPI server exposing the Nexa SDK as an OpenAI-compatible API.
Wraps nexaai.LLM as /v1/chat/completions and /v1/models endpoints.

The Nexa SDK (pip install nexaai) is a library-only package with no
built-in HTTP server.  This shim bridges that gap so OpenJarvis can
discover and use Nexa as a standard engine on port 18181.

Usage:
    uvicorn openjarvis.engine.nexa_shim:app \
        --host 127.0.0.1 --port 18181

    Or via the CLI:
        jarvis host <model_path> --backend nexa
"""

from __future__ import annotations

import os
import time
import uuid

try:
    import nexaai  # type: ignore[import-untyped]
except ImportError:
    import sys

    print("nexa_shim: pip install nexaai", file=sys.stderr)
    sys.exit(1)

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Nexa SDK Shim")

# Model path set via NEXA_MODEL_PATH env var or overridden at startup.
_MODEL_PATH: str = os.environ.get("NEXA_MODEL_PATH", "")
_PLUGIN_ID: str = os.environ.get("NEXA_PLUGIN_ID", "cpu_gpu")
_llm: nexaai.LLM | None = None


def _get_llm() -> nexaai.LLM:
    global _llm
    if _llm is None:
        if not _MODEL_PATH:
            raise RuntimeError(
                "NEXA_MODEL_PATH not set. "
                "Export it or pass --model to the server."
            )
        _llm = nexaai.LLM(_MODEL_PATH, plugin_id=_PLUGIN_ID)
    return _llm


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "nexa"
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
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "detail": str(exc)}, status_code=503,
        )


@app.get("/v1/models")
def list_models() -> JSONResponse:
    model_name = os.path.basename(_MODEL_PATH) or "nexa"
    return JSONResponse({
        "object": "list",
        "data": [
            {"id": model_name, "object": "model", "owned_by": "nexa"},
        ],
    })


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest) -> JSONResponse:
    llm = _get_llm()
    prompt = _build_prompt(req.messages)
    config = nexaai.GenerationConfig(max_tokens=req.max_tokens)
    result = llm.generate(prompt, config=config)
    text = result.text if hasattr(result, "text") else str(result)
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    return JSONResponse({
        "id": cid,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
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
