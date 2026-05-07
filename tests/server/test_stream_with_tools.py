"""Tests for the tool-aware streaming branch in routes._handle_stream.

Verifies that StreamChunks carrying tool_calls / content / finish_reason
get rendered as SSE chunks with the matching DeltaMessage fields.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, List

import pytest

from openjarvis.engine._stubs import StreamChunk
from openjarvis.server.models import (
    ChatCompletionRequest,
    ChatMessage,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


async def _yield_chunks(*chunks: StreamChunk) -> AsyncIterator[StreamChunk]:
    for c in chunks:
        yield c


class _FakeEngine:
    """Engine stub that returns a pre-canned StreamChunk sequence."""

    def __init__(self, chunks: List[StreamChunk]):
        self._chunks = chunks
        self.calls: List[dict] = []

    def stream_full(
        self,
        messages: Any,
        *,
        model: str,
        tools: List[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append({"model": model, "tools": tools})
        return _yield_chunks(*self._chunks)


def _parse_sse(payload: str) -> List[dict]:
    """Pull ``data: {...}`` JSON envelopes out of an SSE byte stream."""
    out: List[dict] = []
    for line in payload.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        body = line[len("data: "):]
        if body == "[DONE]":
            continue
        try:
            out.append(json.loads(body))
        except json.JSONDecodeError:
            continue
    return out


async def _collect_stream(engine, model: str, req: ChatCompletionRequest) -> str:
    from openjarvis.server.routes import _handle_stream

    response = await _handle_stream(engine, model, req)
    body_iter = response.body_iterator
    parts: List[str] = []
    async for piece in body_iter:
        if isinstance(piece, bytes):
            piece = piece.decode("utf-8")
        parts.append(piece)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_chunk_is_emitted_in_sse(monkeypatch):
    """A StreamChunk(tool_calls=[...]) must surface as delta.tool_calls in SSE."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    engine = _FakeEngine([
        StreamChunk(
            tool_calls=[
                {"id": "call_1", "type": "function",
                 "function": {"name": "n8n_list_workflows", "arguments": "{}"}},
            ],
        ),
        StreamChunk(finish_reason="tool_calls"),
    ])
    req = ChatCompletionRequest(
        model="claude-sonnet-4-6",
        messages=[ChatMessage(role="user", content="list workflows")],
        tools=[{"type": "function", "function": {"name": "n8n_list_workflows"}}],
        stream=True,
    )

    body = await _collect_stream(engine, "claude-sonnet-4-6", req)
    chunks = _parse_sse(body)

    # Must contain at least one chunk whose first choice has tool_calls populated.
    tool_call_chunks = [
        c for c in chunks
        if c["choices"] and c["choices"][0]["delta"].get("tool_calls")
    ]
    assert tool_call_chunks, (
        "expected an SSE chunk with delta.tool_calls; got chunks:\n"
        + json.dumps(chunks, indent=2)
    )
    tool_calls = tool_call_chunks[0]["choices"][0]["delta"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "n8n_list_workflows"

    # Engine was called with tools forwarded.
    assert engine.calls and engine.calls[0]["tools"]
    assert engine.calls[0]["tools"][0]["function"]["name"] == "n8n_list_workflows"


@pytest.mark.asyncio
async def test_content_chunk_still_works_with_tools(monkeypatch):
    """Content deltas in the tools path render as delta.content (existing shape)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    engine = _FakeEngine([
        StreamChunk(content="Sure, let me check."),
        StreamChunk(finish_reason="stop"),
    ])
    req = ChatCompletionRequest(
        model="claude-sonnet-4-6",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[{"type": "function", "function": {"name": "noop"}}],
        stream=True,
    )

    body = await _collect_stream(engine, "claude-sonnet-4-6", req)
    chunks = _parse_sse(body)
    content_chunks = [
        c for c in chunks
        if c["choices"] and c["choices"][0]["delta"].get("content") == "Sure, let me check."
    ]
    assert content_chunks


@pytest.mark.asyncio
async def test_no_tools_skips_stream_full(monkeypatch):
    """When req.tools is empty/None, stream_full() must NOT be called.

    The legacy path may pick stream_local / stream_cloud / engine.stream
    depending on the model; the key invariant for this PR is that
    stream_full (the new tools-aware path) is reached only when tools
    are actually present.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    class _LegacyEngine:
        def __init__(self):
            self.stream_full_calls = 0

        def stream_full(self, *args, **kwargs):
            self.stream_full_calls += 1
            return _yield_chunks()

        async def stream(self, messages, *, model, temperature=0.7, max_tokens=1024):
            yield "ok"

    engine = _LegacyEngine()
    req = ChatCompletionRequest(
        model="claude-haiku-4-5",
        messages=[ChatMessage(role="user", content="hi")],
        tools=None,
        stream=True,
    )
    # We don't care which legacy branch handles the request; we only
    # assert the new tools-aware branch was NOT chosen. Errors from the
    # legacy branch (e.g. missing OPENROUTER key) are fine — the SSE
    # error chunk still gets emitted, but stream_full was never called.
    await _collect_stream(engine, "claude-haiku-4-5", req)
    assert engine.stream_full_calls == 0
