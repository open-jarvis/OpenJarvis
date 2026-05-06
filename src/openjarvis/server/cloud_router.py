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
_GROQ_PREFIXES = ("llama-3", "llama3-", "mixtral-", "gemma2-", "whisper-large-v3", "groq/")
_DEEPSEEK_PREFIXES = ("deepseek-",)
_CEREBRAS_PREFIXES = ("cerebras/",)
_SAMBANOVA_PREFIXES = ("sambanova/",)
_KIMI_PREFIXES = ("moonshot-", "kimi-",)
_V0_PREFIXES = ("v0-",)
_GLM_PREFIXES = ("glm-", "glm/", "chatglm-")
_HF_PREFIXES = ("huggingface/", "hf/")
_GITHUB_PREFIXES = ("github/",)

# HuggingFace orgs that host local-only quantised models — never route to cloud.
_LOCAL_HF_ORGS = (
    "mlx-community/",
    "bartowski/",
    "unsloth/",
    "lmstudio-community/",
)

# All env-var names the cloud router may need — read from os.environ at startup.
_CLOUD_KEY_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_B",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "CEREBRAS_API_KEY",
    "SAMBANOVA_API_KEY",
    "KIMI_API_KEY",
    "MOONSHOT_API_KEY",
    "V0_API_KEY",
    "MINIMAX_API_KEY",
    "GLM_API_KEY",
    "ZHIPUAI_API_KEY",
    "Bridge_Zbigmodel_api",
    "HF_API_KEY",
    "HUGGINGFACE_API_KEY",
    "HF_TOKEN",
    "GITHUB_MODELS_TOKEN",
    "GITHUB_PAT",
    "GITHUB_TOKEN",
    # Feature-flag env vars
    "GROQ_ENABLED",
    "DEEPSEEK_ENABLED",
    "OPENROUTER_ENABLED",
    "CEREBRAS_ENABLED",
    "SAMBANOVA_ENABLED",
    "KIMI_ENABLED",
    "V0_ENABLED",
    "HF_ENABLED",
    "GLM_ENABLED",
    "GITHUB_MODELS_ENABLED",
    "MINIMAX_ENABLED",
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
    # Process env overrides file values (Railway / Docker env vars take precedence)
    for name in _CLOUD_KEY_NAMES:
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
    if any(model.startswith(p) for p in _DEEPSEEK_PREFIXES):
        return "deepseek"
    if any(model.startswith(p) for p in _GROQ_PREFIXES):
        return "groq"
    if any(model.startswith(p) for p in _CEREBRAS_PREFIXES):
        return "cerebras"
    if any(model.startswith(p) for p in _SAMBANOVA_PREFIXES):
        return "sambanova"
    if any(model.startswith(p) for p in _KIMI_PREFIXES):
        return "kimi"
    if any(model.startswith(p) for p in _V0_PREFIXES):
        return "v0"
    if any(model.startswith(p) for p in _GLM_PREFIXES):
        return "glm"
    if any(model.startswith(p) for p in _GITHUB_PREFIXES):
        return "github"
    if any(model.startswith(p) for p in _HF_PREFIXES):
        return "hf"
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

    # Auth via header (not URL query param) so the key never appears in
    # error messages, logs, or HTTP referrers if anything goes wrong.
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:streamGenerateContent?alt=sse"
    )
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
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

    elif provider == "groq":
        # Strip an optional "groq/" namespace prefix so users can disambiguate
        # Groq from OpenRouter when the model id contains a slash.
        bare_model = model.removeprefix("groq/")
        async for token in _stream_openai(
            bare_model,
            messages,
            temperature,
            max_tokens,
            base_url="https://api.groq.com/openai/v1",
            api_key_name="GROQ_API_KEY",
        ):
            yield token

    elif provider == "deepseek":
        async for token in _stream_openai(
            model,
            messages,
            temperature,
            max_tokens,
            base_url="https://api.deepseek.com/v1",
            api_key_name="DEEPSEEK_API_KEY",
        ):
            yield token

    elif provider == "cerebras":
        # Strip the "cerebras/" namespace prefix before sending to the API
        bare_model = model.removeprefix("cerebras/")
        async for token in _stream_openai(
            bare_model,
            messages,
            temperature,
            max_tokens,
            base_url="https://api.cerebras.ai/v1",
            api_key_name="CEREBRAS_API_KEY",
        ):
            yield token

    elif provider == "sambanova":
        # Strip the "sambanova/" namespace prefix before sending to the API
        bare_model = model.removeprefix("sambanova/")
        async for token in _stream_openai(
            bare_model,
            messages,
            temperature,
            max_tokens,
            base_url="https://api.sambanova.ai/v1",
            api_key_name="SAMBANOVA_API_KEY",
        ):
            yield token

    elif provider == "kimi":
        async for token in _stream_openai(
            model,
            messages,
            temperature,
            max_tokens,
            base_url="https://api.moonshot.cn/v1",
            api_key_name="KIMI_API_KEY",
        ):
            yield token

    elif provider == "v0":
        async for token in _stream_openai(
            model,
            messages,
            temperature,
            max_tokens,
            base_url="https://api.v0.dev/v1",
            api_key_name="V0_API_KEY",
        ):
            yield token

    elif provider == "glm":
        # Strip an optional "glm/" namespace prefix; the upstream API uses
        # bare model names like "glm-4-plus".
        bare_model = model.removeprefix("glm/")
        # GLM key fallback chain: GLM_API_KEY -> ZHIPUAI_API_KEY -> Bridge_Zbigmodel_api
        keys = _load_keys()
        resolved_key_name = next(
            (n for n in ("GLM_API_KEY", "ZHIPUAI_API_KEY", "Bridge_Zbigmodel_api")
             if keys.get(n)),
            "GLM_API_KEY",
        )
        async for token in _stream_openai(
            bare_model,
            messages,
            temperature,
            max_tokens,
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key_name=resolved_key_name,
        ):
            yield token

    elif provider == "github":
        # GitHub Models — Azure-hosted, OpenAI-compatible. Strip "github/" prefix.
        bare_model = model.removeprefix("github/")
        keys = _load_keys()
        resolved_key_name = next(
            (n for n in ("GITHUB_MODELS_TOKEN", "GITHUB_PAT", "GITHUB_TOKEN")
             if keys.get(n)),
            "GITHUB_PAT",
        )
        async for token in _stream_openai(
            bare_model,
            messages,
            temperature,
            max_tokens,
            base_url="https://models.inference.ai.azure.com",
            api_key_name=resolved_key_name,
        ):
            yield token

    elif provider == "hf":
        # HuggingFace router (OpenAI-compatible). Strip the "hf/" or
        # "huggingface/" prefix; the upstream model id includes the org/repo.
        bare_model = model.removeprefix("hf/").removeprefix("huggingface/")
        keys = _load_keys()
        resolved_key_name = next(
            (n for n in ("HF_API_KEY", "HUGGINGFACE_API_KEY", "HF_TOKEN")
             if keys.get(n)),
            "HF_API_KEY",
        )
        async for token in _stream_openai(
            bare_model,
            messages,
            temperature,
            max_tokens,
            base_url="https://router.huggingface.co/v1",
            api_key_name=resolved_key_name,
        ):
            yield token

    else:
        raise ValueError(f"Unknown cloud provider for model: {model!r}")
