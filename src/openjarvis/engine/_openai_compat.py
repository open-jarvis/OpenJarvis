"""Shared base for OpenAI-compatible ``/v1/`` engines."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

import httpx

from openjarvis.core.types import Message
from openjarvis.engine._base import (
    EngineConnectionError,
    InferenceEngine,
    estimate_prompt_tokens,
    messages_to_dicts,
)
from openjarvis.engine._stubs import StreamChunk

logger = logging.getLogger(__name__)


class _OpenAICompatibleEngine(InferenceEngine):
    """Base for engines that serve the OpenAI ``/v1/chat/completions`` API."""

    engine_id: str = ""
    _default_host: str = "http://localhost:8000"
    _api_prefix: str = "/v1"

    def __init__(self, host: str | None = None, *, timeout: float = 600.0) -> None:
        self._host = (host or self._default_host).rstrip("/")
        self._client = httpx.Client(base_url=self._host, timeout=timeout)

    # -- InferenceEngine interface ------------------------------------------

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            **kwargs,
        }
        # Default to tool_choice=auto when tools are provided
        if "tools" in payload and "tool_choice" not in payload:
            payload["tool_choice"] = "auto"
        try:
            url = f"{self._api_prefix}/chat/completions"
            resp = self._client.post(url, json=payload)
            if resp.status_code == 400 and "tools" in payload:
                payload.pop("tools", None)
                payload.pop("tool_choice", None)
                resp = self._client.post(url, json=payload)
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"{self.engine_id} engine not reachable at {self._host}"
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
        # Ensure prompt_tokens reflects the full prompt size (including
        # system prompt and all conversation history).
        # OpenAI-compat APIs (vLLM, SGLang) report full counts — KV
        # caching is transparent, so evaluated == full.
        reported_prompt = usage.get("prompt_tokens", 0)
        estimated_prompt = estimate_prompt_tokens(messages)
        prompt_tokens = max(reported_prompt, estimated_prompt)
        completion_tokens = usage.get("completion_tokens", 0)
        result: Dict[str, Any] = {
            "content": choice["message"].get("content") or "",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "prompt_tokens_evaluated": reported_prompt or prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": data.get("model", model),
            "finish_reason": choice.get("finish_reason", "stop"),
        }
        # Extract tool calls if present
        raw_tool_calls = choice["message"].get("tool_calls", [])
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

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs,
        }
        # Default to tool_choice=auto when tools are provided
        if "tools" in payload and "tool_choice" not in payload:
            payload["tool_choice"] = "auto"
        try:
            url = f"{self._api_prefix}/chat/completions"
            with self._client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"{self.engine_id} engine not reachable at {self._host}"
            ) from exc

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]:
        """Yield StreamChunks with content, tool_calls, and finish_reason."""
        msg_dicts = messages_to_dicts(messages)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs,
        }
        if "tools" in payload and "tool_choice" not in payload:
            payload["tool_choice"] = "auto"
        try:
            url = f"{self._api_prefix}/chat/completions"
            with self._client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    finish = choice.get("finish_reason")
                    content = delta.get("content")
                    tool_calls = delta.get("tool_calls")
                    usage = chunk.get("usage")

                    if content or tool_calls or finish or usage:
                        yield StreamChunk(
                            content=content,
                            tool_calls=tool_calls,
                            finish_reason=finish,
                            usage=usage,
                        )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"{self.engine_id} engine not reachable at {self._host}"
            ) from exc

    def list_models(self) -> List[str]:
        try:
            resp = self._client.get(f"{self._api_prefix}/models")
            resp.raise_for_status()
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
        ) as exc:
            logger.warning(
                "Failed to list models from %s at %s: %s",
                self.engine_id,
                self._host,
                exc,
            )
            return []
        data = resp.json()
        return [m["id"] for m in data.get("data", [])]

    def health(self) -> bool:
        try:
            resp = self._client.get(f"{self._api_prefix}/models", timeout=2.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug(
                "%s health check failed at %s: %s",
                self.engine_id,
                self._host,
                exc,
            )
            return False

    def close(self) -> None:
        self._client.close()


__all__ = ["_OpenAICompatibleEngine"]
