"""Direct cloud API router — bypasses the engine system entirely.

Reads API keys from ~/.openjarvis/cloud-keys.env at request time so
it works even when the server was started without cloud keys in its
environment.  Uses httpx directly so no cloud SDK packages are required.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Sequence

import httpx

from openjarvis.core.types import Message

# ---------------------------------------------------------------------------
# Key / provider detection
# ---------------------------------------------------------------------------

_CLOUD_ENV_FILE = Path.home() / ".openjarvis" / "cloud-keys.env"

_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-", "chatgpt-")
_ANTHROPIC_PREFIXES = ("claude-",)
_GOOGLE_PREFIXES = ("gemini-",)
_MINIMAX_PREFIXES = ("MiniMax-",)

# HuggingFace orgs that host local-only quantised models — never route to cloud.
_LOCAL_HF_ORGS = (
    "mlx-community/",
    "bartowski/",
    "unsloth/",
    "lmstudio-community/",
)


def _load_keys() -> dict[str, str]:
    """Read cloud-keys.env from disk every call so live updates are picked up."""
    keys: dict[str, str] = {}
    # File first, then fall back to process environment
    if _CLOUD_ENV_FILE.exists():
        for raw in _CLOUD_ENV_FILE.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    # Process env can override (e.g. during testing)
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "MINIMAX_API_KEY",
    ):
        val = os.environ.get(name)
        if val:
            keys[name] = val
    return keys


def get_provider(model: str) -> str | None:
    """Return the provider for a model name, or None if it's a local model."""
    if any(model.startswith(p) for p in _OPENAI_PREFIXES):
        return "openai"
    if any(model.startswith(p) for p in _ANTHROPIC_PREFIXES):
        return "anthropic"
    if any(model.startswith(p) for p in _GOOGLE_PREFIXES):
        return "google"
    if any(model.startswith(p) for p in _MINIMAX_PREFIXES):
        return "minimax"
    if any(model.startswith(org) for org in _LOCAL_HF_ORGS):
        return None  # local model, never route to cloud
    if "/" in model:  # openrouter format: "meta-llama/llama-3-8b"
        return "openrouter"
    return None


def is_cloud_model(model: str) -> bool:
    """Return True if the model is served by a cloud provider."""
    return get_provider(model) is not None


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


def _to_openai_msgs(messages: Sequence[Message]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        out.append({"role": role, "content": m.content or ""})
    return out


def _to_anthropic_msgs(
    messages: Sequence[Message],
) -> tuple[str, list[dict[str, Any]]]:
    """Return (system_text, chat_messages) in Anthropic format."""
    system_text = ""
    chat: list[dict[str, Any]] = []
    for m in messages:
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        if role == "system":
            system_text = m.content or ""
        else:
            # Anthropic only allows "user" and "assistant"
            ar = "user" if role != "assistant" else "assistant"
            chat.append({"role": ar, "content": m.content or ""})
    return system_text, chat


def _to_google_contents(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Convert to Google Gemini content format."""
    contents = []
    for m in messages:
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        if role == "system":
            # Gemini doesn't have a system role in the contents array;
            # prepend as a user message.
            contents.append({"role": "user", "parts": [{"text": m.content or ""}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": m.content or ""}]})
        else:
            contents.append({"role": "user", "parts": [{"text": m.content or ""}]})
    return contents


# ---------------------------------------------------------------------------
# Streaming generators
# ---------------------------------------------------------------------------


async def _stream_openai(
    model: str,
    messages: Sequence[Message],
    temperature: float,
    max_tokens: int,
    base_url: str = "https://api.openai.com/v1",
    api_key_name: str = "OPENAI_API_KEY",
) -> AsyncIterator[str]:
    keys = _load_keys()
    api_key = keys.get(api_key_name, "")
    if not api_key:
        raise ValueError(f"{api_key_name} not set — add it in the Cloud Models tab")

    payload = {
        "model": model,
        "messages": _to_openai_msgs(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content") or ""
                    if delta:
                        yield delta
                except Exception:
                    pass


async def _stream_anthropic(
    model: str,
    messages: Sequence[Message],
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[str]:
    keys = _load_keys()
    api_key = keys.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set — add it in the Cloud Models tab")

    system_text, chat_msgs = _to_anthropic_msgs(messages)
    payload: dict[str, Any] = {
        "model": model,
        "messages": chat_msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if system_text:
        payload["system"] = system_text

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                try:
                    event = json.loads(data)
                    if event.get("type") == "content_block_delta":
                        text = event.get("delta", {}).get("text", "")
                        if text:
                            yield text
                except Exception:
                    pass


async def _stream_google(
    model: str,
    messages: Sequence[Message],
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[str]:
    keys = _load_keys()
    api_key = keys.get("GEMINI_API_KEY") or keys.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set — add it in the Cloud Models tab")

    contents = _to_google_contents(messages)
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:streamGenerateContent?alt=sse&key={api_key}"
    )

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                try:
                    chunk = json.loads(data)
                    parts = (
                        chunk.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [])
                    )
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            yield text
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Local (Ollama) direct streaming — bypasses engine routing entirely
# ---------------------------------------------------------------------------


def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


async def stream_local(
    model: str,
    messages: Sequence[Message],
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """Stream tokens directly from Ollama, bypassing the engine system."""
    payload = {
        "model": model,
        "messages": _to_openai_msgs(messages),
        "stream": True,
        # Disable extended thinking (Qwen3.5 etc.) — when enabled all tokens
        # go into the 'thinking' field and 'content' stays empty.
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    host = _ollama_host()
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream("POST", f"{host}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
                except Exception:
                    pass


async def list_local_models() -> list[str]:
    """Return Ollama model names directly from the Ollama API."""
    host = _ollama_host()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{host}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def stream_cloud(
    model: str,
    messages: Sequence[Message],
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """Stream tokens from a cloud provider for the given model."""
    provider = get_provider(model)

    if provider == "openai":
        async for token in _stream_openai(model, messages, temperature, max_tokens):
            yield token

    elif provider == "anthropic":
        async for token in _stream_anthropic(model, messages, temperature, max_tokens):
            yield token

    elif provider == "google":
        async for token in _stream_google(model, messages, temperature, max_tokens):
            yield token

    elif provider == "openrouter":
        keys = _load_keys()
        api_key = keys.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY not set — add it in the Cloud Models tab"
            )
        async for token in _stream_openai(
            model,
            messages,
            temperature,
            max_tokens,
            base_url="https://openrouter.ai/api/v1",
            api_key_name="OPENROUTER_API_KEY",
        ):
            yield token

    elif provider == "minimax":
        keys = _load_keys()
        api_key = keys.get("MINIMAX_API_KEY", "")
        if not api_key:
            raise ValueError("MINIMAX_API_KEY not set — add it in the Cloud Models tab")
        async for token in _stream_openai(
            model,
            messages,
            temperature,
            max_tokens,
            base_url="https://api.minimax.io/v1",
            api_key_name="MINIMAX_API_KEY",
        ):
            yield token

    else:
        raise ValueError(f"Unknown cloud provider for model: {model!r}")
