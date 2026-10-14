"""Foundry Local inference engine (Windows ML / OpenAI-compatible HTTP).

Foundry Local exposes an OpenAI-compatible ``/v1`` server. The listen port is
assigned when the server starts, so callers should prefer
:func:`discover_foundry_host` over the fallback default. Agents, tools, and
``jarvis serve`` use this engine through the normal ``InferenceEngine``
registry — it is not a side demo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any, Dict, Sequence
from urllib.parse import urlparse

import httpx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message
from openjarvis.engine._base import EngineConnectionError, messages_to_dicts
from openjarvis.engine._openai_compat import _OpenAICompatibleEngine

logger = logging.getLogger(__name__)

# Documented fallback only. Real deployments write the discovered host into
# ``[engine.foundry_local] host`` (or ``FOUNDRY_LOCAL_HOST``).
FOUNDRY_LOCAL_FALLBACK_HOST = "http://localhost:5273"
_CPU_PROVIDER_MARKERS = ("cpu", "mlas")
_ACCEL_PROVIDER_MARKERS = (
    "cuda",
    "tensorrt",
    "nvtensorrtrtx",
    "webgpu",
    "qnn",
    "openvino",
    "vitisai",
    "dml",
    "directml",
)
_URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_TRIVIAL_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Return a constant acknowledgement. No side effects.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _normalize_foundry_base(url: str) -> str:
    """Strip Foundry status and OpenAI prefixes so the engine can append ``/v1``."""
    parsed = urlparse(url.strip().rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        return url.strip().rstrip("/")
    path = parsed.path.rstrip("/")
    for suffix in ("/openai/status", "/openai", "/v1"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    base = f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    return base or f"{parsed.scheme}://{parsed.netloc}"


def _parse_host_from_status_text(raw: str) -> str | None:
    """Extract an HTTP base URL from Foundry CLI status output."""
    if not raw:
        return None
    stripped = raw.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            for key in (
                "endpoint",
                "baseUrl",
                "base_url",
                "uri",
                "url",
                "openai_endpoint",
            ):
                value = payload.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    return _normalize_foundry_base(value)
            nested = payload.get("service") or payload.get("openai") or {}
            if isinstance(nested, dict):
                for key in ("endpoint", "url", "uri"):
                    value = nested.get(key)
                    if isinstance(value, str) and value.startswith("http"):
                        return _normalize_foundry_base(value)
    match = _URL_RE.search(raw)
    if match:
        return _normalize_foundry_base(match.group(0))
    return None


def discover_foundry_host() -> str:
    """Return Foundry Local's OpenAI-compatible base URL.

    Order: ``FOUNDRY_LOCAL_HOST`` / ``FOUNDRY_LOCAL_ENDPOINT``, then
    ``foundry server status`` (current CLI) / ``foundry service status``
    (legacy), then the documented localhost fallback.
    """
    for env_name in ("FOUNDRY_LOCAL_HOST", "FOUNDRY_LOCAL_ENDPOINT"):
        env_host = os.environ.get(env_name, "").strip()
        if env_host:
            return _normalize_foundry_base(env_host)

    foundry = shutil.which("foundry")
    if foundry:
        for args in (
            [foundry, "server", "status", "--json"],
            [foundry, "server", "status"],
            [foundry, "service", "status", "--json"],
            [foundry, "service", "status"],
        ):
            try:
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            host = _parse_host_from_status_text(
                (result.stdout or "") + "\n" + (result.stderr or "")
            )
            if host:
                return host

    return FOUNDRY_LOCAL_FALLBACK_HOST


def classify_execution_provider(name: str) -> tuple[str, bool]:
    """Return ``(canonical_name, is_cpu_fallback)`` for a Foundry EP string."""
    raw = (name or "").strip() or "unknown"
    lowered = raw.lower()
    is_accel = any(marker in lowered for marker in _ACCEL_PROVIDER_MARKERS)
    is_cpu = any(marker in lowered for marker in _CPU_PROVIDER_MARKERS)
    fallback = is_cpu and not is_accel
    if fallback:
        return raw, True
    if is_accel:
        return raw, False
    return raw, is_cpu


def probe_execution_provider(host: str) -> dict[str, Any]:
    """Ask Foundry which execution provider is active.

    Returns a dict with ``execution_provider``, ``cpu_fallback``, and
    ``source``. Missing data is represented as ``unknown`` / ``False``.
    """
    base = _normalize_foundry_base(host)
    candidates = (
        f"{base}/openai/status",
        f"{base}/status",
        f"{base}/v1/status",
    )
    headers = {}
    api_key = os.environ.get("FOUNDRY_LOCAL_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=3.0, headers=headers or None) as client:
            for url in candidates:
                try:
                    resp = client.get(url)
                except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
                    continue
                if resp.status_code != 200:
                    continue
                try:
                    payload = resp.json()
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                for key in (
                    "executionProvider",
                    "execution_provider",
                    "ep",
                    "provider",
                    "device",
                ):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        name, fallback = classify_execution_provider(value)
                        return {
                            "execution_provider": name,
                            "cpu_fallback": fallback,
                            "source": url,
                        }
    except (httpx.HTTPError, OSError) as exc:
        logger.debug("Foundry execution-provider probe failed: %s", exc)

    return {
        "execution_provider": "unknown",
        "cpu_fallback": False,
        "source": "",
    }


def infer_cpu_fallback_from_model(model: str | None) -> bool:
    """True when the catalog id itself indicates a CPU EP (e.g. *-generic-cpu)."""
    name = (model or "").lower()
    return "generic-cpu" in name or name.endswith("-cpu") or ":cpu" in name


def check_tool_calling(
    engine: "FoundryLocalEngine",
    model: str,
) -> dict[str, Any]:
    """POST a trivial tool schema and record whether Foundry accepts it.

    Does not retry without tools (the shared OpenAI-compat client does). A
    400 here means this model cannot drive agent tool loops. 512 tokens
    gives reasoning models (Qwen3, DeepSeek-R1, Phi-4-mini-reasoning) room
    to spend their ``reasoning_content`` budget before emitting the actual
    ``tool_calls`` — 64 cut them off mid-thought and read as unsupported.

    Uses ``tool_choice: "required"``, not ``"auto"``. This checks *capability*
    (can the model emit a well-formed tool_calls payload at all), not default
    judgment. With ``"auto"``, Phi-4-mini-instruct declined the contrived
    "Call ping now." probe outright (and even flatly refused it once) while
    still answering real tool-shaped questions wrong by guessing instead of
    calling a real calculator tool — "auto" measures whether the model
    *bothers*, which a trivial no-op probe can't represent, not whether it
    *can*.
    """
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Call ping now."}],
        "temperature": 0,
        "max_tokens": 512,
        "tools": _TRIVIAL_TOOL,
        "tool_choice": "required",
        "stream": False,
    }
    try:
        resp = engine._client.post(
            f"{engine._api_prefix}/chat/completions", json=payload
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        return {
            "supported": False,
            "reason": f"Foundry Local was not reachable: {exc}",
        }
    if resp.status_code == 400:
        body = resp.text.strip()[:400]
        return {
            "supported": False,
            "reason": (
                "This Foundry Local model rejected tool calling "
                f"(HTTP 400). Agent runs that need tools will fail. {body}"
            ).strip(),
        }
    if resp.status_code >= 400:
        body = resp.text.strip()[:400]
        return {
            "supported": False,
            "reason": (
                f"Foundry Local returned HTTP {resp.status_code} "
                f"during the tool-calling check. {body}"
            ).strip(),
        }
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return {
            "supported": False,
            "reason": "Foundry Local returned a non-JSON tool-calling response.",
        }
    choices = data.get("choices") or []
    choice = choices[0] if choices else {}
    message = (choice.get("message") if choice else {}) or {}
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        return {"supported": True, "reason": ""}
    if choice.get("finish_reason") == "length":
        return {
            "supported": False,
            "reason": (
                "Foundry Local truncated the response at the token limit "
                "before emitting a tool_calls payload (this model spends "
                "tokens on reasoning_content first). Agent tool loops need "
                "a larger max_tokens budget for this model."
            ),
        }
    return {
        "supported": False,
        "reason": (
            "Foundry Local accepted the request but returned no tool_calls. "
            "Agent runs that need tools will fail rather than hang."
        ),
    }


@EngineRegistry.register("foundry_local")
class FoundryLocalEngine(_OpenAICompatibleEngine):
    """OpenAI-compatible client for Foundry Local + Windows ML."""

    engine_id = "foundry_local"
    _default_host = FOUNDRY_LOCAL_FALLBACK_HOST
    _api_prefix = "/v1"

    def __init__(
        self,
        host: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 600.0,
    ) -> None:
        resolved = host or discover_foundry_host()
        super().__init__(host=resolved, api_key=api_key, timeout=timeout)

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate, failing closed when Foundry rejects tool schemas.

        The shared OpenAI-compat client retries without tools on HTTP 400 so
        chat still works on servers that do not implement tools. Agent
        workflows on Foundry must not silently drop tools — that looks like a
        hang as the model narrates instead of calling. When ``tools`` is
        present, a 400 becomes :class:`EngineConnectionError`.
        """
        if "tools" not in kwargs:
            return super().generate(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        payload: Dict[str, Any] = {
            "model": self._resolve_model_id(model),
            "messages": messages_to_dicts(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            **kwargs,
        }
        if "tool_choice" not in payload:
            payload["tool_choice"] = "auto"
        try:
            url = f"{self._api_prefix}/chat/completions"
            resp = self._client.post(url, json=payload)
            if resp.status_code == 400:
                detail = resp.text.strip()[:400]
                raise EngineConnectionError(
                    "Foundry Local rejected tool calling for this model. "
                    "Choose a model with tool support or the simple agent. "
                    f"{detail}".strip()
                )
            resp.raise_for_status()
        except EngineConnectionError:
            raise
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"{self.engine_id} engine not reachable at {self._host}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text.strip()
            raise EngineConnectionError(
                f"{self.engine_id} engine at {self._host} returned HTTP "
                f"{exc.response.status_code}"
                + (f": {error_detail}" if error_detail else "")
            ) from exc
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return {
                "content": "",
                "usage": data.get("usage", {}),
                "model": data.get("model", model),
                "finish_reason": "error",
            }
        choice = choices[0]
        usage = data.get("usage", {})
        result: Dict[str, Any] = {
            "content": (choice.get("message") or {}).get("content") or "",
            "usage": usage,
            "model": data.get("model", model),
            "finish_reason": choice.get("finish_reason", "stop"),
        }
        raw_tool_calls = (choice.get("message") or {}).get("tool_calls") or []
        if raw_tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", "{}"),
                }
                for tc in raw_tool_calls
            ]
        return result


__all__ = [
    "FOUNDRY_LOCAL_FALLBACK_HOST",
    "FoundryLocalEngine",
    "check_tool_calling",
    "classify_execution_provider",
    "discover_foundry_host",
    "infer_cpu_fallback_from_model",
    "probe_execution_provider",
]
