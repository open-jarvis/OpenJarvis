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


class EngineContextLengthError(EngineConnectionError):
    """The prompt exceeds the served model's maximum context window.

    Subclasses ``EngineConnectionError`` so existing ``except
    EngineConnectionError`` handlers keep catching it, while callers that want a
    distinct, user-facing "conversation too long" message can branch on this type
    (or the ``is_context_length_error`` marker) instead of surfacing a generic
    engine failure.
    """

    is_context_length_error: bool = True


# Substrings that identify an upstream 400 as a context-window overflow (vLLM,
# SGLang, and OpenAI-compatible servers phrase this a few different ways).
_CONTEXT_LENGTH_MARKERS = (
    "context length",
    "maximum context",
    "context window",
    "maximum_context",
    "context_length_exceeded",
    "reduce the length",
    "please reduce",
    "too many tokens",
    "maximum number of tokens",
)


def _looks_like_context_length(detail: str) -> bool:
    """True when an upstream error body reads like a context-window overflow."""
    low = (detail or "").lower()
    return any(marker in low for marker in _CONTEXT_LENGTH_MARKERS)


class _OpenAICompatibleEngine(InferenceEngine):
    """Base for engines that serve the OpenAI ``/v1/chat/completions`` API."""

    engine_id: str = ""
    _default_host: str = "http://localhost:8000"
    _api_prefix: str = "/v1"

    def __init__(
        self,
        host: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 600.0,
    ) -> None:
        import os

        # Sanitize the engine id for env-var lookup ("openai-compat" ->
        # "OPENAI_COMPAT_..."); shells cannot set hyphenated variable names.
        env_prefix = self.engine_id.upper().replace("-", "_")
        self._host = (
            host or os.environ.get(f"{env_prefix}_HOST") or self._default_host
        ).rstrip("/")
        # Bearer auth for endpoints started with e.g. ``vllm serve --api-key``.
        # Setting it on the client covers generate/stream/stream_full/
        # list_models/health alike; ``None`` keeps requests header-free.
        self._api_key = api_key or os.environ.get(f"{env_prefix}_API_KEY") or None
        headers = (
            {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
        )
        # Retained for the async streaming path (built per-call below) and so the
        # bounded request timeout is applied to streaming reads, not just the
        # synchronous methods (a wedged token read now fails at ``timeout`` rather
        # than hanging the caller for the httpx default).
        self._timeout = timeout
        self._headers = headers
        # Injection seam for tests: an ``httpx.MockTransport`` swapped in here lets
        # the async stream path be exercised with a mocked transport and no real
        # server. ``None`` in production so httpx uses its default networking.
        self._async_transport: httpx.AsyncBaseTransport | None = None
        self._client = httpx.Client(
            base_url=self._host, timeout=timeout, headers=headers
        )

    def _make_async_client(self) -> httpx.AsyncClient:
        """Build a per-call async client that honours the configured timeout.

        A fresh client per stream keeps the async lifecycle fully self-contained
        (opened and closed by ``async with``), so a wedged upstream read is bounded
        by ``timeout`` and no async resource outlives the request.
        """
        return httpx.AsyncClient(
            base_url=self._host,
            timeout=self._timeout,
            headers=self._headers,
            transport=self._async_transport,
        )

    def _raise_stream_http_error(self, status: int, detail: str) -> None:
        """Map an upstream streaming HTTP error to a clean engine exception."""
        detail = (detail or "").strip()
        if status == 400 and _looks_like_context_length(detail):
            raise EngineContextLengthError(
                "The conversation is too long for the model's context window. "
                "Start a new chat or shorten the conversation, then try again."
            )
        detail_suffix = f": {detail}" if detail else ""
        raise EngineConnectionError(
            f"{self.engine_id} engine at {self._host} returned HTTP "
            f"{status}{detail_suffix}"
        )

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
        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text.strip()
            if exc.response.status_code == 404:
                detail_suffix = (
                    f" Response body: {error_detail}" if error_detail else ""
                )
                raise EngineConnectionError(
                    f"{self.engine_id} engine at {self._host} returned 404 for "
                    f"{self._api_prefix}/chat/completions. Make sure this port "
                    "is running an OpenAI-compatible chat server, not another "
                    f"local web service.{detail_suffix}"
                ) from exc
            detail_suffix = f": {error_detail}" if error_detail else ""
            raise EngineConnectionError(
                f"{self.engine_id} engine at {self._host} returned HTTP "
                f"{exc.response.status_code}{detail_suffix}"
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
        url = f"{self._api_prefix}/chat/completions"
        try:
            # ASYNC streaming: a per-call ``httpx.AsyncClient`` + ``aiter_lines``
            # never blocks the event loop between tokens (the previous SYNC
            # ``httpx.Client`` + ``iter_lines`` inside this ``async def`` blocked
            # the single uvicorn worker on every inter-token wait, serializing all
            # concurrent chats and letting one wedged read freeze the whole API).
            async with self._make_async_client() as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        # Load the (short) error body before touching ``.text``:
                        # a streaming response is otherwise unread.
                        await resp.aread()
                        self._raise_stream_http_error(resp.status_code, resp.text)
                    async for line in resp.aiter_lines():
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
            # A wedged upstream read trips ``timeout`` (ReadTimeout) and is mapped
            # here, so the request fails cleanly at the configured bound instead of
            # hanging indefinitely.
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
        url = f"{self._api_prefix}/chat/completions"
        try:
            # ASYNC streaming (see ``stream``): non-blocking per-call client so
            # rich streaming never stalls the event loop and honours ``timeout``.
            async with self._make_async_client() as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        self._raise_stream_http_error(resp.status_code, resp.text)
                    async for line in resp.aiter_lines():
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


__all__ = ["_OpenAICompatibleEngine", "EngineContextLengthError"]
