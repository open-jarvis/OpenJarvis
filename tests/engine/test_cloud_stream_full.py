"""Tests for CloudEngine.stream_full, _stream_full_openai, _stream_full_anthropic,
and _prepare_anthropic_messages."""

from __future__ import annotations

from typing import Any, List
from unittest.mock import MagicMock

import pytest

from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.engine._stubs import StreamChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cloud_engine(**overrides: Any) -> Any:
    """Create a CloudEngine without calling __init__ (no env vars needed)."""
    from openjarvis.engine.cloud import CloudEngine

    engine = CloudEngine.__new__(CloudEngine)
    engine._openai_client = overrides.get("openai_client")
    engine._anthropic_client = overrides.get("anthropic_client")
    engine._google_client = overrides.get("google_client")
    engine._openrouter_client = overrides.get("openrouter_client")
    engine._minimax_client = overrides.get("minimax_client")
    return engine


def _openai_chunk(
    *,
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
) -> MagicMock:
    """Build a mock OpenAI streaming chunk."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def _openai_tool_call_delta(
    *,
    index: int = 0,
    tc_id: str = "",
    name: str = "",
    arguments: str = "",
) -> MagicMock:
    tc = MagicMock()
    tc.index = index
    tc.id = tc_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


# ---------------------------------------------------------------------------
# _stream_full_openai tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_full_openai_content():
    """Mock OpenAI streaming response with content chunks."""
    mock_client = MagicMock()
    chunks = [
        _openai_chunk(content="Hello"),
        _openai_chunk(content=" world"),
        _openai_chunk(finish_reason="stop"),
    ]
    mock_client.chat.completions.create.return_value = iter(chunks)

    engine = _make_cloud_engine(openai_client=mock_client)
    msgs = [Message(role=Role.USER, content="hi")]

    result: List[StreamChunk] = []
    async for sc in engine._stream_full_openai(
        msgs,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=100,
    ):
        result.append(sc)

    assert len(result) == 3
    assert result[0].content == "Hello"
    assert result[1].content == " world"
    assert result[2].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_full_openai_tool_calls():
    """Mock response with tool_call deltas, verify StreamChunk.tool_calls format."""
    mock_client = MagicMock()
    tc1 = _openai_tool_call_delta(index=0, tc_id="call_1", name="calc", arguments="")
    tc2 = _openai_tool_call_delta(index=0, tc_id="", name="", arguments='{"x": 1}')
    chunks = [
        _openai_chunk(tool_calls=[tc1]),
        _openai_chunk(tool_calls=[tc2]),
        _openai_chunk(finish_reason="tool_calls"),
    ]
    mock_client.chat.completions.create.return_value = iter(chunks)

    engine = _make_cloud_engine(openai_client=mock_client)
    msgs = [Message(role=Role.USER, content="calc")]

    result: List[StreamChunk] = []
    async for sc in engine._stream_full_openai(
        msgs,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=100,
    ):
        result.append(sc)

    assert result[0].tool_calls is not None
    assert result[0].tool_calls[0]["function"]["name"] == "calc"
    assert result[0].tool_calls[0]["id"] == "call_1"
    assert result[1].tool_calls[0]["function"]["arguments"] == '{"x": 1}'
    assert result[2].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_stream_full_openai_finish_reason():
    """Verify finish_reason='tool_calls' and 'stop' propagated correctly."""
    mock_client = MagicMock()
    chunks_stop = [
        _openai_chunk(content="ok"),
        _openai_chunk(finish_reason="stop"),
    ]
    mock_client.chat.completions.create.return_value = iter(chunks_stop)

    engine = _make_cloud_engine(openai_client=mock_client)
    msgs = [Message(role=Role.USER, content="hi")]

    result = []
    async for sc in engine._stream_full_openai(
        msgs,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=100,
    ):
        result.append(sc)

    assert result[-1].finish_reason == "stop"

    # Now test tool_calls finish
    tc = _openai_tool_call_delta(index=0, tc_id="c1", name="fn", arguments="{}")
    chunks_tc = [
        _openai_chunk(tool_calls=[tc]),
        _openai_chunk(finish_reason="tool_calls"),
    ]
    mock_client.chat.completions.create.return_value = iter(chunks_tc)

    result2 = []
    async for sc in engine._stream_full_openai(
        msgs,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=100,
    ):
        result2.append(sc)

    assert result2[-1].finish_reason == "tool_calls"


# ---------------------------------------------------------------------------
# _stream_full_anthropic tests
# ---------------------------------------------------------------------------


def _anthropic_event(event_type: str, **kwargs: Any) -> MagicMock:
    """Build a mock Anthropic stream event."""
    event = MagicMock()
    event.type = event_type
    for k, v in kwargs.items():
        setattr(event, k, v)
    return event


@pytest.mark.asyncio
async def test_stream_full_anthropic_content():
    """Mock Anthropic stream events with text content."""
    # Build content_block_start with text type
    text_block = MagicMock()
    text_block.type = "text"

    # Build text delta
    text_delta = MagicMock()
    text_delta.type = "text_delta"
    text_delta.text = "Hello world"

    # Build message_delta with stop
    msg_delta = MagicMock()
    msg_delta.stop_reason = "end_turn"

    events = [
        _anthropic_event("content_block_start", content_block=text_block),
        _anthropic_event("content_block_delta", delta=text_delta),
        _anthropic_event("message_delta", delta=msg_delta),
    ]

    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=iter(events))
    mock_stream.__exit__ = MagicMock(return_value=False)

    mock_anthropic = MagicMock()
    mock_anthropic.messages.stream.return_value = mock_stream

    engine = _make_cloud_engine(anthropic_client=mock_anthropic)
    msgs = [Message(role=Role.USER, content="hi")]

    result: List[StreamChunk] = []
    async for sc in engine._stream_full_anthropic(
        msgs,
        model="claude-sonnet-4-20250514",
        temperature=0.7,
        max_tokens=100,
    ):
        result.append(sc)

    # Should have text content and a finish reason
    content_chunks = [r for r in result if r.content is not None]
    assert len(content_chunks) >= 1
    assert content_chunks[0].content == "Hello world"

    finish_chunks = [r for r in result if r.finish_reason is not None]
    assert len(finish_chunks) == 1
    assert finish_chunks[0].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_full_anthropic_tool_calls():
    """Mock Anthropic tool_use events, verify OpenAI-delta-format tool_calls."""
    # content_block_start with tool_use
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "toolu_123"
    tool_block.name = "get_weather"

    # input_json_delta
    json_delta = MagicMock()
    json_delta.type = "input_json_delta"
    json_delta.partial_json = '{"city": "Berlin"}'

    # message_delta with tool_use stop
    msg_delta = MagicMock()
    msg_delta.stop_reason = "tool_use"

    events = [
        _anthropic_event("content_block_start", content_block=tool_block),
        _anthropic_event("content_block_delta", delta=json_delta),
        _anthropic_event("message_delta", delta=msg_delta),
    ]

    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=iter(events))
    mock_stream.__exit__ = MagicMock(return_value=False)

    mock_anthropic = MagicMock()
    mock_anthropic.messages.stream.return_value = mock_stream

    engine = _make_cloud_engine(anthropic_client=mock_anthropic)
    msgs = [Message(role=Role.USER, content="weather?")]

    result: List[StreamChunk] = []
    async for sc in engine._stream_full_anthropic(
        msgs,
        model="claude-sonnet-4-20250514",
        temperature=0.7,
        max_tokens=100,
    ):
        result.append(sc)

    # First chunk: tool_use start with name
    assert result[0].tool_calls is not None
    assert result[0].tool_calls[0]["function"]["name"] == "get_weather"
    assert result[0].tool_calls[0]["id"] == "toolu_123"

    # Second chunk: arguments fragment
    assert result[1].tool_calls is not None
    assert result[1].tool_calls[0]["function"]["arguments"] == '{"city": "Berlin"}'

    # Third chunk: finish with tool_calls
    assert result[2].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_stream_full_anthropic_finish_reason():
    """message_delta with stop_reason='tool_use' maps to finish_reason='tool_calls'."""
    msg_delta_tool = MagicMock()
    msg_delta_tool.stop_reason = "tool_use"

    msg_delta_stop = MagicMock()
    msg_delta_stop.stop_reason = "end_turn"

    # Test tool_use -> tool_calls
    events_tool = [_anthropic_event("message_delta", delta=msg_delta_tool)]
    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=iter(events_tool))
    mock_stream.__exit__ = MagicMock(return_value=False)

    mock_anthropic = MagicMock()
    mock_anthropic.messages.stream.return_value = mock_stream

    engine = _make_cloud_engine(anthropic_client=mock_anthropic)
    msgs = [Message(role=Role.USER, content="test")]

    result = []
    async for sc in engine._stream_full_anthropic(
        msgs,
        model="claude-sonnet-4-20250514",
        temperature=0.7,
        max_tokens=100,
    ):
        result.append(sc)
    assert result[0].finish_reason == "tool_calls"

    # Test end_turn -> stop
    events_stop = [_anthropic_event("message_delta", delta=msg_delta_stop)]
    mock_stream2 = MagicMock()
    mock_stream2.__enter__ = MagicMock(return_value=iter(events_stop))
    mock_stream2.__exit__ = MagicMock(return_value=False)
    mock_anthropic.messages.stream.return_value = mock_stream2

    result2 = []
    async for sc in engine._stream_full_anthropic(
        msgs,
        model="claude-sonnet-4-20250514",
        temperature=0.7,
        max_tokens=100,
    ):
        result2.append(sc)
    assert result2[0].finish_reason == "stop"


# ---------------------------------------------------------------------------
# _prepare_anthropic_messages tests
# ---------------------------------------------------------------------------


def test_prepare_anthropic_messages_system():
    """System message extracted separately from chat messages."""
    engine = _make_cloud_engine()
    msgs = [
        Message(role=Role.SYSTEM, content="You are helpful"),
        Message(role=Role.USER, content="Hello"),
    ]

    system_text, chat_msgs = engine._prepare_anthropic_messages(msgs)
    assert system_text == "You are helpful"
    assert len(chat_msgs) == 1
    assert chat_msgs[0]["role"] == "user"
    assert chat_msgs[0]["content"] == "Hello"


def test_prepare_anthropic_messages_tool_result():
    """Tool role converted to user + tool_result content block."""
    engine = _make_cloud_engine()
    msgs = [
        Message(role=Role.USER, content="What's the weather?"),
        Message(
            role=Role.TOOL,
            content='{"temp": 20}',
            tool_call_id="call_abc",
        ),
    ]

    system_text, chat_msgs = engine._prepare_anthropic_messages(msgs)
    assert system_text == ""
    assert len(chat_msgs) == 2
    # Second message is the tool result wrapped as user
    tool_msg = chat_msgs[1]
    assert tool_msg["role"] == "user"
    assert isinstance(tool_msg["content"], list)
    assert tool_msg["content"][0]["type"] == "tool_result"
    assert tool_msg["content"][0]["tool_use_id"] == "call_abc"
    assert tool_msg["content"][0]["content"] == '{"temp": 20}'


def test_prepare_anthropic_messages_tool_calls():
    """Assistant with tool_calls converted to content blocks with tool_use."""
    engine = _make_cloud_engine()
    msgs = [
        Message(
            role=Role.ASSISTANT,
            content="Let me check.",
            tool_calls=[
                ToolCall(
                    id="call_1", name="get_weather", arguments='{"city": "Berlin"}'
                ),
            ],
        ),
    ]

    system_text, chat_msgs = engine._prepare_anthropic_messages(msgs)
    assert len(chat_msgs) == 1
    blocks = chat_msgs[0]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == "Let me check."
    assert blocks[1]["type"] == "tool_use"
    assert blocks[1]["id"] == "call_1"
    assert blocks[1]["name"] == "get_weather"
    assert blocks[1]["input"] == {"city": "Berlin"}


# ---------------------------------------------------------------------------
# stream_full routing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_full_routes_to_anthropic():
    """model='claude-xxx' routes to _stream_full_anthropic."""
    msg_delta = MagicMock()
    msg_delta.stop_reason = "end_turn"
    events = [_anthropic_event("message_delta", delta=msg_delta)]
    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=iter(events))
    mock_stream.__exit__ = MagicMock(return_value=False)

    mock_anthropic = MagicMock()
    mock_anthropic.messages.stream.return_value = mock_stream

    engine = _make_cloud_engine(anthropic_client=mock_anthropic)
    msgs = [Message(role=Role.USER, content="test")]

    result = []
    async for sc in engine.stream_full(msgs, model="claude-sonnet-4-20250514"):
        result.append(sc)

    # Verify Anthropic client was used
    mock_anthropic.messages.stream.assert_called_once()
    assert any(r.finish_reason is not None for r in result)


@pytest.mark.asyncio
async def test_stream_full_routes_to_openai():
    """model='gpt-xxx' routes to _stream_full_openai."""
    mock_client = MagicMock()
    chunks = [
        _openai_chunk(content="hi"),
        _openai_chunk(finish_reason="stop"),
    ]
    mock_client.chat.completions.create.return_value = iter(chunks)

    engine = _make_cloud_engine(openai_client=mock_client)
    msgs = [Message(role=Role.USER, content="test")]

    result = []
    async for sc in engine.stream_full(msgs, model="gpt-4o"):
        result.append(sc)

    # Verify OpenAI client was used
    mock_client.chat.completions.create.assert_called_once()
    assert result[0].content == "hi"
    assert result[1].finish_reason == "stop"
