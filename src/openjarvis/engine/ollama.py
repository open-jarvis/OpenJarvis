"""Ollama inference engine backend."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

import httpx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message
from openjarvis.engine._base import (
    EngineConnectionError,
    InferenceEngine,
    estimate_prompt_tokens,
    messages_to_dicts,
)
from openjarvis.engine._stubs import StreamChunk

logger = logging.getLogger(__name__)


@EngineRegistry.register("ollama")
class OllamaEngine(InferenceEngine):
    """Ollama backend via its native HTTP API."""

    engine_id = "ollama"

    _DEFAULT_HOST = "http://localhost:11434"

    def __init__(
        self,
        host: str | None = None,
        *,
        timeout: float = 1800.0,
    ) -> None:
        # Priority: explicit host (from config.toml) > OLLAMA_HOST env var > default
        if host is None:
            env_host = os.environ.get("OLLAMA_HOST")
            host = env_host or self._DEFAULT_HOST
        self._host = host.rstrip("/")
        self._client = httpx.Client(base_url=self._host, timeout=timeout)
        # Last stream usage — captured from Ollama's final chunk
        self._last_stream_usage: Dict[str, int] = {}

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        msg_dicts = messages_to_dicts(messages)
        # Ollama expects tool_call arguments as dicts, not JSON strings
        for md in msg_dicts:
            for tc in md.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        pass
        payload: Dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": kwargs.get("num_ctx", 8192),
            },
        }
        # Disable extended thinking by default (Qwen3.5 etc.).
        # When enabled, thinking tokens consume the entire budget and
        # the visible content comes back empty.
        if "think" not in kwargs:
            payload["think"] = False
        elif kwargs["think"] is not None:
            payload["think"] = kwargs["think"]
        # Pass tools if provided
        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        # Apply structured output / JSON mode
        response_format = kwargs.get("response_format")
        if response_format is not None:
            from openjarvis.engine._stubs import ResponseFormat

            if isinstance(response_format, ResponseFormat):
                payload["format"] = "json"
            elif isinstance(response_format, dict):
                payload["format"] = "json"
        try:
            resp = self._client.post("/api/chat", json=payload)
            if resp.status_code == 400 and tools:
                # Model may not support function calling -- retry without tools
                payload.pop("tools", None)
                resp = self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"Ollama not reachable at {self._host}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response else ""
            raise RuntimeError(
                f"Ollama returned {exc.response.status_code}: {body}"
            ) from exc
        data = resp.json()
        # prompt_eval_count = tokens actually evaluated (KV-cache-aware).
        # estimate_prompt_tokens = full prompt size (for cost comparison).
        # We report both so downstream can use the right one:
        #   prompt_tokens        → full size (what cloud would charge)
        #   prompt_tokens_evaluated → actual compute (with KV cache)
        reported_prompt = data.get("prompt_eval_count", 0)
        estimated_prompt = estimate_prompt_tokens(messages)
        prompt_tokens = max(reported_prompt, estimated_prompt)
        prompt_tokens_evaluated = (
            reported_prompt if reported_prompt > 0 else prompt_tokens
        )
        completion_tokens = data.get("eval_count", 0)
        content = data.get("message", {}).get("content", "")
        result: Dict[str, Any] = {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "prompt_tokens_evaluated": prompt_tokens_evaluated,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": data.get("model", model),
            "finish_reason": "stop",
        }
        # Extract timing from Ollama response (nanoseconds → seconds)
        result["ttft"] = data.get("prompt_eval_duration", 0) / 1e9
        result["engine_timing"] = {
            k: data[k]
            for k in (
                "total_duration",
                "load_duration",
                "prompt_eval_duration",
                "eval_duration",
            )
            if k in data
        }
        # Extract tool calls if present
        raw_tool_calls = data.get("message", {}).get("tool_calls", [])
        if raw_tool_calls:
            tool_calls = []
            for i, tc in enumerate(raw_tool_calls):
                raw_args = tc.get("function", {}).get(
                    "arguments",
                    "{}",
                )
                tool_calls.append(
                    {
                        "id": tc.get("id", f"call_{i}"),
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": (
                            json.dumps(raw_args)
                            if isinstance(raw_args, dict)
                            else raw_args
                        ),
                    }
                )
            result["tool_calls"] = tool_calls
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
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": kwargs.get("num_ctx", 8192),
            },
        }
        try:
            with self._client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done", False):
                        reported_prompt = chunk.get("prompt_eval_count", 0)
                        est_prompt = estimate_prompt_tokens(messages)
                        full_prompt = max(reported_prompt, est_prompt)
                        evaluated = (
                            reported_prompt if reported_prompt > 0 else full_prompt
                        )
                        comp = chunk.get("eval_count", 0)
                        self._last_stream_usage = {
                            "prompt_tokens": full_prompt,
                            "prompt_tokens_evaluated": evaluated,
                            "completion_tokens": comp,
                            "total_tokens": full_prompt + comp,
                        }
                        break
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"Ollama not reachable at {self._host}"
            ) from exc

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Yield ``StreamChunk``s including tool_calls.

        Unlike the default ``stream_full`` in the base class (which wraps
        ``stream()`` and drops tools), this posts to ``/api/chat`` with
        ``tools`` from kwargs and parses tool_calls out of the streamed
        response. Falls back to a tools-less retry on 400 (mirrors
        ``generate()``'s behaviour for models that don't support tools).
        """
        msg_dicts = messages_to_dicts(messages)
        for md in msg_dicts:
            for tc in md.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        pass

        payload: Dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": kwargs.get("num_ctx", 8192),
            },
        }
        if "think" not in kwargs:
            payload["think"] = False
        elif kwargs["think"] is not None:
            payload["think"] = kwargs["think"]

        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        async for chunk in self._run_stream(
            payload, messages, retry_without_tools=bool(tools)
        ):
            yield chunk

    async def _run_stream(
        self,
        payload: Dict[str, Any],
        messages: Sequence[Message],
        *,
        retry_without_tools: bool,
    ) -> AsyncIterator[StreamChunk]:
        """Execute the streaming request and yield parsed StreamChunks."""
        try:
            with self._client.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code == 400 and retry_without_tools:
                    # Model doesn't support tools — retry without them.
                    payload.pop("tools", None)
                    async for c in self._run_stream(
                        payload, messages, retry_without_tools=False
                    ):
                        yield c
                    return
                resp.raise_for_status()

                finish_reason: str | None = None
                for line in resp.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    message = chunk.get("message", {}) or {}
                    content = message.get("content", "")
                    raw_tool_calls = message.get("tool_calls") or []

                    if content:
                        yield StreamChunk(content=content)

                    if raw_tool_calls:
                        # Ollama emits fully-formed tool_calls in a single
                        # chunk (not fragmented). Convert to the
                        # OpenAI-delta fragment shape that agent_manager_routes
                        # expects in _merge_tool_call_fragments.
                        fragments: List[Dict[str, Any]] = []
                        for i, tc in enumerate(raw_tool_calls):
                            fn = tc.get("function", {}) or {}
                            raw_args = fn.get("arguments", "{}")
                            args_str = (
                                json.dumps(raw_args)
                                if isinstance(raw_args, dict)
                                else str(raw_args)
                            )
                            fragments.append(
                                {
                                    "index": i,
                                    "id": tc.get("id", f"call_{i}"),
                                    "type": "function",
                                    "function": {
                                        "name": fn.get("name", ""),
                                        "arguments": args_str,
                                    },
                                }
                            )
                        yield StreamChunk(tool_calls=fragments)
                        finish_reason = "tool_calls"

                    if chunk.get("done", False):
                        reported_prompt = chunk.get("prompt_eval_count", 0)
                        est_prompt = estimate_prompt_tokens(messages)
                        full_prompt = max(reported_prompt, est_prompt)
                        evaluated = (
                            reported_prompt if reported_prompt > 0 else full_prompt
                        )
                        comp = chunk.get("eval_count", 0)
                        self._last_stream_usage = {
                            "prompt_tokens": full_prompt,
                            "prompt_tokens_evaluated": evaluated,
                            "completion_tokens": comp,
                            "total_tokens": full_prompt + comp,
                        }
                        if finish_reason is None:
                            finish_reason = chunk.get("done_reason") or "stop"
                        yield StreamChunk(
                            finish_reason=finish_reason,
                            usage=dict(self._last_stream_usage),
                        )
                        break
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"Ollama not reachable at {self._host}"
            ) from exc

    def list_models(self) -> List[str]:
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
        ) as exc:
            logger.warning(
                "Failed to list models from Ollama at %s: %s",
                self._host,
                exc,
            )
            return []
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]

    def health(self) -> bool:
        try:
            resp = self._client.get("/api/tags", timeout=2.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("Ollama health check failed at %s: %s", self._host, exc)
            return False

    def close(self) -> None:
        self._client.close()


__all__ = ["OllamaEngine"]
