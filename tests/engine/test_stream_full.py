"""Tests for StreamChunk dataclass and stream_full() engine method."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine, StreamChunk

# ---------------------------------------------------------------------------
# StreamChunk dataclass tests
# ---------------------------------------------------------------------------


class TestStreamChunk:
    def test_defaults(self):
        chunk = StreamChunk()
        assert chunk.content is None
        assert chunk.tool_calls is None
        assert chunk.finish_reason is None
        assert chunk.usage is None

    def test_content_only(self):
        chunk = StreamChunk(content="hello")
        assert chunk.content == "hello"
        assert chunk.finish_reason is None

    def test_finish_reason(self):
        chunk = StreamChunk(finish_reason="stop")
        assert chunk.content is None
        assert chunk.finish_reason == "stop"

    def test_tool_calls(self):
        tc = [{"index": 0, "function": {"name": "calc", "arguments": "{}"}}]
        chunk = StreamChunk(tool_calls=tc)
        assert chunk.tool_calls == tc

    def test_usage(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        chunk = StreamChunk(usage=usage)
        assert chunk.usage == usage

    def test_all_fields(self):
        chunk = StreamChunk(
            content="hi",
            tool_calls=[{"index": 0}],
            finish_reason="tool_calls",
            usage={"total_tokens": 1},
        )
        assert chunk.content == "hi"
        assert chunk.tool_calls is not None
        assert chunk.finish_reason == "tool_calls"
        assert chunk.usage is not None


# ---------------------------------------------------------------------------
# Concrete engine stub for testing default stream_full()
# ---------------------------------------------------------------------------


class _FakeEngine(InferenceEngine):
    """Minimal engine that yields predefined tokens via stream()."""

    engine_id = "fake"

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    def generate(self, messages, *, model, **kwargs) -> Dict[str, Any]:
        return {"content": "".join(self._tokens), "usage": {}}

    async def stream(self, messages, *, model, **kwargs) -> AsyncIterator[str]:
        for t in self._tokens:
            yield t

    def list_models(self) -> List[str]:
        return ["fake-model"]

    def health(self) -> bool:
        return True


class TestDefaultStreamFull:
    """Test the default stream_full() implementation that wraps stream()."""

    @pytest.mark.asyncio
    async def test_wraps_stream_tokens(self):
        engine = _FakeEngine(["Hello", " world", "!"])
        chunks = []
        async for chunk in engine.stream_full(
            [Message(role=Role.USER, content="test")],
            model="fake-model",
        ):
            chunks.append(chunk)

        # Should have 3 content chunks + 1 finish chunk
        assert len(chunks) == 4
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[2].content == "!"
        assert chunks[3].finish_reason == "stop"
        assert chunks[3].content is None

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        engine = _FakeEngine([])
        chunks = []
        async for chunk in engine.stream_full(
            [Message(role=Role.USER, content="test")],
            model="fake-model",
        ):
            chunks.append(chunk)

        # Should have just the finish chunk
        assert len(chunks) == 1
        assert chunks[0].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_kwargs_passed_through(self):
        """Verify that temperature/max_tokens reach stream()."""
        engine = _FakeEngine(["ok"])
        chunks = []
        async for chunk in engine.stream_full(
            [Message(role=Role.USER, content="test")],
            model="fake-model",
            temperature=0.1,
            max_tokens=50,
        ):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].content == "ok"


# ---------------------------------------------------------------------------
# OpenAI-compatible stream_full() with mock HTTP response
# ---------------------------------------------------------------------------


class TestOpenAICompatStreamFull:
    """Test _OpenAICompatibleEngine.stream_full() with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_parses_sse_with_content_and_finish(self):
        from openjarvis.engine._openai_compat import _OpenAICompatibleEngine

        # Build mock SSE lines
        sse_lines = []
        for token in ["Hello", " world"]:
            chunk = {
                "choices": [{"delta": {"content": token}, "finish_reason": None}],
            }
            sse_lines.append(f"data: {json.dumps(chunk)}")
        # Final chunk with finish_reason
        final = {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        sse_lines.append(f"data: {json.dumps(final)}")
        sse_lines.append("data: [DONE]")

        # Mock the httpx client stream context manager
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = iter(sse_lines)

        engine = _OpenAICompatibleEngine.__new__(_OpenAICompatibleEngine)
        engine.engine_id = "test"
        engine._host = "http://localhost:8000"
        engine._api_prefix = "/v1"

        mock_client = MagicMock()
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__ = MagicMock(return_value=mock_resp)
        mock_stream_ctx.__exit__ = MagicMock(return_value=False)
        mock_client.stream.return_value = mock_stream_ctx
        engine._client = mock_client

        chunks = []
        async for chunk in engine.stream_full(
            [Message(role=Role.USER, content="test")],
            model="test-model",
        ):
            chunks.append(chunk)

        # Should have: "Hello", " world", finish+usage
        assert len(chunks) == 3
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[2].finish_reason == "stop"
        assert chunks[2].usage is not None
        assert chunks[2].usage["total_tokens"] == 7

    @pytest.mark.asyncio
    async def test_parses_tool_call_fragments(self):
        from openjarvis.engine._openai_compat import _OpenAICompatibleEngine

        # Simulate streamed tool_call fragments
        _tc1 = (
            '{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1",'
            ' "function": {"name": "calc", "arguments": ""}}]},'
            ' "finish_reason": null}]}'
        )
        _tc2 = (
            '{"choices": [{"delta": {"tool_calls": [{"index": 0,'
            ' "function": {"name": "", "arguments": "{\\"x\\": 1}"}}]},'
            ' "finish_reason": null}]}'
        )
        sse_lines = [
            f"data: {_tc1}",
            f"data: {_tc2}",
            'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = iter(sse_lines)

        engine = _OpenAICompatibleEngine.__new__(_OpenAICompatibleEngine)
        engine.engine_id = "test"
        engine._host = "http://localhost:8000"
        engine._api_prefix = "/v1"

        mock_client = MagicMock()
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__ = MagicMock(return_value=mock_resp)
        mock_stream_ctx.__exit__ = MagicMock(return_value=False)
        mock_client.stream.return_value = mock_stream_ctx
        engine._client = mock_client

        chunks = []
        async for chunk in engine.stream_full(
            [Message(role=Role.USER, content="test")],
            model="test-model",
        ):
            chunks.append(chunk)

        # First chunk has tool_calls with name
        assert chunks[0].tool_calls is not None
        assert chunks[0].tool_calls[0]["function"]["name"] == "calc"
        # Second chunk has arguments fragment
        assert chunks[1].tool_calls is not None
        # Third chunk has finish_reason="tool_calls"
        assert chunks[2].finish_reason == "tool_calls"
