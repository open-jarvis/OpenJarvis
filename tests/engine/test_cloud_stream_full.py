"""Tests for CloudEngine.stream_full, _stream_full_openai, _stream_full_anthropic,
and _prepare_anthropic_messages."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from types import ModuleType, SimpleNamespace
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock

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
    engine._deepseek_client = overrides.get("deepseek_client")
    engine._openai_async_client = overrides.get("openai_async_client")
    engine._anthropic_async_client = overrides.get("anthropic_async_client")
    engine._openrouter_async_client = overrides.get("openrouter_async_client")
    engine._minimax_async_client = overrides.get("minimax_async_client")
    engine._deepseek_async_client = overrides.get("deepseek_async_client")
    return engine


def _openai_chunk(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
) -> MagicMock:
    """Build a mock OpenAI streaming chunk."""
    delta = MagicMock()
    delta.content = content
    delta.reasoning_content = reasoning_content
    delta.tool_calls = tool_calls
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


class _AsyncChunks:
    def __init__(self, chunks: list[MagicMock]) -> None:
        self._chunks = iter(chunks)

    def __aiter__(self) -> _AsyncChunks:
        return self

    async def __anext__(self) -> MagicMock:
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self) -> None:
        return None


def _async_openai_client(chunks: list[MagicMock]) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_AsyncChunks(chunks))
    return client


class _AsyncAnthropicStream:
    def __init__(self, events: list[MagicMock]) -> None:
        self._events = iter(events)

    async def __aenter__(self) -> _AsyncAnthropicStream:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __aiter__(self) -> _AsyncAnthropicStream:
        return self

    async def __anext__(self) -> MagicMock:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def get_final_message(self) -> None:
        return None


def _async_anthropic_client(*event_rounds: list[MagicMock]) -> MagicMock:
    client = MagicMock()
    client.messages.stream.side_effect = [
        _AsyncAnthropicStream(events) for events in event_rounds
    ]
    return client


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


class _GoogleConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def _google_stream_chunk(
    *parts: Any,
    text: str | None = None,
    usage_metadata: Any = None,
) -> Any:
    candidates = []
    if parts:
        candidates = [SimpleNamespace(content=SimpleNamespace(parts=list(parts)))]
    return SimpleNamespace(
        text=text,
        candidates=candidates,
        usage_metadata=usage_metadata,
    )


def _google_types_modules() -> dict[str, ModuleType]:
    types = ModuleType("google.genai.types")
    types.GenerateContentConfig = _GoogleConfig
    genai = ModuleType("google.genai")
    genai.types = types
    google = ModuleType("google")
    google.genai = genai
    return {"google": google, "google.genai": genai, "google.genai.types": types}


# ---------------------------------------------------------------------------
# _stream_full_openai tests
# ---------------------------------------------------------------------------


def test_only_deepseek_declares_semantic_reasoning_stream() -> None:
    engine = _make_cloud_engine()

    assert engine.supports_semantic_reasoning_stream("deepseek-v4-flash") is True
    assert engine.supports_semantic_reasoning_stream("gpt-4o") is False


@pytest.mark.asyncio
async def test_deepseek_stream_full_wait_is_cooperative() -> None:
    provider_started = asyncio.Event()
    release_provider = asyncio.Event()
    heartbeat_ran = asyncio.Event()

    class AsyncChunks:
        def __init__(self) -> None:
            self._chunks = iter(
                [
                    _openai_chunk(content="Visible"),
                    _openai_chunk(finish_reason="stop"),
                ]
            )

        def __aiter__(self) -> AsyncChunks:
            return self

        async def __anext__(self) -> MagicMock:
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        async def close(self) -> None:
            return None

    class Completions:
        async def create(self, **_kwargs: object) -> AsyncChunks:
            provider_started.set()
            await release_provider.wait()
            return AsyncChunks()

    async_client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    sync_client = MagicMock()
    sync_client.chat.completions.create.side_effect = AssertionError(
        "synchronous provider path used"
    )
    engine = _make_cloud_engine(
        deepseek_client=sync_client,
        deepseek_async_client=async_client,
    )

    async def heartbeat() -> None:
        await provider_started.wait()
        heartbeat_ran.set()
        release_provider.set()

    heartbeat_task = asyncio.create_task(heartbeat())
    chunks = [
        chunk
        async for chunk in engine._stream_full_openai(
            [Message(role=Role.USER, content="hi")],
            model="deepseek-v4-flash",
            temperature=0.7,
            max_tokens=100,
        )
    ]
    await heartbeat_task

    assert heartbeat_ran.is_set()
    assert [chunk.content for chunk in chunks] == ["Visible", None]
    sync_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_anthropic_stream_full_uses_async_provider_iteration() -> None:
    text_delta = SimpleNamespace(type="text_delta", text="Visible")
    stop_delta = SimpleNamespace(stop_reason="end_turn")
    events = [
        SimpleNamespace(type="content_block_delta", delta=text_delta),
        SimpleNamespace(type="message_delta", delta=stop_delta),
    ]

    class Stream:
        async def __aenter__(self) -> Stream:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def __aiter__(self) -> AsyncIterator[object]:
            return self

        async def __anext__(self) -> object:
            if events:
                return events.pop(0)
            raise StopAsyncIteration

        async def get_final_message(self) -> None:
            return None

    async_client = SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **_kwargs: Stream())
    )
    sync_client = MagicMock()
    sync_client.messages.stream.side_effect = AssertionError(
        "synchronous Anthropic path used"
    )
    engine = _make_cloud_engine(
        anthropic_client=sync_client,
        anthropic_async_client=async_client,
    )

    chunks = [
        chunk
        async for chunk in engine._stream_full_anthropic(
            [Message(role=Role.USER, content="hi")],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=100,
        )
    ]

    assert [chunk.content for chunk in chunks] == ["Visible", None]
    assert chunks[-1].finish_reason == "stop"
    sync_client.messages.stream.assert_not_called()


@pytest.mark.asyncio
async def test_close_releases_all_async_provider_clients() -> None:
    closed: list[str] = []

    class AsyncClient:
        def __init__(self, name: str) -> None:
            self._name = name

        async def close(self) -> None:
            closed.append(self._name)

    engine = _make_cloud_engine(
        openai_async_client=AsyncClient("openai"),
        anthropic_async_client=AsyncClient("anthropic"),
        openrouter_async_client=AsyncClient("openrouter"),
        minimax_async_client=AsyncClient("minimax"),
        deepseek_async_client=AsyncClient("deepseek"),
    )
    engine._codex_client = None

    engine.close()
    await asyncio.sleep(0)

    assert closed == ["openai", "anthropic", "openrouter", "minimax", "deepseek"]
    assert engine._openai_async_client is None
    assert engine._anthropic_async_client is None
    assert engine._openrouter_async_client is None
    assert engine._minimax_async_client is None
    assert engine._deepseek_async_client is None


@pytest.mark.asyncio
async def test_stream_full_openai_content():
    """Mock OpenAI streaming response with content chunks."""
    chunks = [
        _openai_chunk(content="Hello"),
        _openai_chunk(content=" world"),
        _openai_chunk(finish_reason="stop"),
    ]
    mock_client = _async_openai_client(chunks)

    engine = _make_cloud_engine(openai_async_client=mock_client)
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
async def test_stream_full_openai_separates_reasoning_content():
    chunks = [
        _openai_chunk(reasoning_content="private one"),
        _openai_chunk(reasoning_content=" private two"),
        _openai_chunk(content="Visible"),
        _openai_chunk(finish_reason="stop"),
    ]
    mock_client = _async_openai_client(chunks)

    engine = _make_cloud_engine(deepseek_async_client=mock_client)
    msgs = [Message(role=Role.USER, content="hi")]

    result: List[StreamChunk] = []
    async for sc in engine._stream_full_openai(
        msgs,
        model="deepseek-v4-flash",
        temperature=0.7,
        max_tokens=100,
    ):
        result.append(sc)

    assert [chunk.reasoning_content for chunk in result] == [
        "private one",
        " private two",
        None,
        None,
    ]
    assert [chunk.content for chunk in result] == [None, None, "Visible", None]


@pytest.mark.asyncio
async def test_stream_full_openai_tool_calls():
    """Mock response with tool_call deltas, verify StreamChunk.tool_calls format."""
    tc1 = _openai_tool_call_delta(index=0, tc_id="call_1", name="calc", arguments="")
    tc2 = _openai_tool_call_delta(index=0, tc_id="", name="", arguments='{"x": 1}')
    chunks = [
        _openai_chunk(tool_calls=[tc1]),
        _openai_chunk(tool_calls=[tc2]),
        _openai_chunk(finish_reason="tool_calls"),
    ]
    mock_client = _async_openai_client(chunks)

    engine = _make_cloud_engine(openai_async_client=mock_client)
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
    chunks_stop = [
        _openai_chunk(content="ok"),
        _openai_chunk(finish_reason="stop"),
    ]
    mock_client = _async_openai_client(chunks_stop)

    engine = _make_cloud_engine(openai_async_client=mock_client)
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
    mock_client.chat.completions.create.return_value = _AsyncChunks(chunks_tc)

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

    mock_anthropic = _async_anthropic_client(events)

    engine = _make_cloud_engine(anthropic_async_client=mock_anthropic)
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

    mock_anthropic = _async_anthropic_client(events)

    engine = _make_cloud_engine(anthropic_async_client=mock_anthropic)
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
    events_stop = [_anthropic_event("message_delta", delta=msg_delta_stop)]
    mock_anthropic = _async_anthropic_client(events_tool, events_stop)

    engine = _make_cloud_engine(anthropic_async_client=mock_anthropic)
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
# _stream_full_google tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_full_google_text_only(monkeypatch: pytest.MonkeyPatch):
    """Google text chunks retain their content and finish normally."""
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter(
        [_google_stream_chunk(text="Hello"), _google_stream_chunk(text=" world")]
    )
    engine = _make_cloud_engine(google_client=client)
    engine._thought_sigs = {}
    messages = [Message(role=Role.USER, content="hi")]
    modules = _google_types_modules()

    with monkeypatch.context() as patch:
        for name, module in modules.items():
            patch.setitem(sys.modules, name, module)
        result = [
            chunk
            async for chunk in engine.stream_full(messages, model="gemini-2.5-flash")
        ]

    assert [chunk.content for chunk in result[:-1]] == ["Hello", " world"]
    assert result[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_full_google_preserves_tool_calls(monkeypatch: pytest.MonkeyPatch):
    """Google function_call parts become OpenAI-compatible tool call chunks."""
    function_call = SimpleNamespace(name="get_weather", args={"city": "Berlin"})
    part = SimpleNamespace(
        function_call=function_call, text=None, thought_signature=b"sig"
    )
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter(
        [_google_stream_chunk(part)]
    )
    engine = _make_cloud_engine(google_client=client)
    engine._thought_sigs = {}
    messages = [Message(role=Role.USER, content="weather")]
    modules = _google_types_modules()

    with monkeypatch.context() as patch:
        for name, module in modules.items():
            patch.setitem(sys.modules, name, module)
        result = [
            chunk
            async for chunk in engine.stream_full(
                messages,
                model="gemini-2.5-flash",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "Get weather",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            )
        ]

    tool_call = result[0].tool_calls[0]
    assert tool_call["index"] == 0
    assert tool_call["id"].startswith("google_")
    assert tool_call["type"] == "function"
    assert tool_call["function"] == {
        "name": "get_weather",
        "arguments": '{"city": "Berlin"}',
    }
    assert tool_call["thought_signature"] == b"sig"
    assert engine._thought_sigs[tool_call["id"]] == b"sig"
    assert result[-1].finish_reason == "tool_calls"
    config = client.models.generate_content_stream.call_args.kwargs["config"]
    assert config.tools == [
        {
            "function_declarations": [
                {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]
        }
    ]


@pytest.mark.asyncio
async def test_stream_full_google_preserves_mixed_and_multiple_calls(
    monkeypatch: pytest.MonkeyPatch,
):
    """Google streams retain mixed text and multiple tool calls."""
    weather = SimpleNamespace(name="get_weather", args={"city": "Berlin"})
    calendar = SimpleNamespace(name="get_calendar", args={"day": "Monday"})
    text_part = SimpleNamespace(text="I'll check.", function_call=None)
    weather_part = SimpleNamespace(
        function_call=weather, text=None, thought_signature=None
    )
    calendar_part = SimpleNamespace(
        function_call=calendar, text=None, thought_signature=None
    )
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter(
        [
            _google_stream_chunk(text_part, weather_part),
            _google_stream_chunk(calendar_part),
        ]
    )
    engine = _make_cloud_engine(google_client=client)
    engine._thought_sigs = {}
    modules = _google_types_modules()

    with monkeypatch.context() as patch:
        for name, module in modules.items():
            patch.setitem(sys.modules, name, module)
        result = [
            chunk
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="plan")], model="gemini-2.5-flash"
            )
        ]

    assert result[0].content == "I'll check."
    weather_call = result[1].tool_calls[0]
    calendar_call = result[2].tool_calls[0]
    assert weather_call["index"] == 0
    assert weather_call["function"] == {
        "name": "get_weather",
        "arguments": '{"city": "Berlin"}',
    }
    assert calendar_call["index"] == 1
    assert calendar_call["function"] == {
        "name": "get_calendar",
        "arguments": '{"day": "Monday"}',
    }
    assert weather_call["id"] != calendar_call["id"]
    assert result[-1].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_stream_full_google_keeps_parallel_same_name_calls_distinct(
    monkeypatch: pytest.MonkeyPatch,
):
    """Parallel invocations of one function receive unique indexes and IDs."""
    paris = SimpleNamespace(name="get_weather", args={"city": "Paris"})
    london = SimpleNamespace(name="get_weather", args={"city": "London"})
    parts = [
        SimpleNamespace(function_call=paris, text=None, thought_signature=b"sig"),
        SimpleNamespace(function_call=london, text=None, thought_signature=None),
    ]
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter(
        [_google_stream_chunk(*parts)]
    )
    engine = _make_cloud_engine(google_client=client)
    engine._thought_sigs = {}

    with monkeypatch.context() as patch:
        for name, module in _google_types_modules().items():
            patch.setitem(sys.modules, name, module)
        result = [
            chunk
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="Weather in Paris and London")],
                model="gemini-3-flash-preview",
            )
        ]

    calls = result[0].tool_calls
    assert [call["index"] for call in calls] == [0, 1]
    assert calls[0]["id"] != calls[1]["id"]
    assert [call["function"]["arguments"] for call in calls] == [
        '{"city": "Paris"}',
        '{"city": "London"}',
    ]


@pytest.mark.asyncio
async def test_stream_full_google_ids_are_unique_across_requests(
    monkeypatch: pytest.MonkeyPatch,
):
    """Shared engines keep signatures isolated between conversations."""
    first_part = SimpleNamespace(
        function_call=SimpleNamespace(name="get_weather", args={"city": "Paris"}),
        text=None,
        thought_signature=b"paris-sig",
    )
    second_part = SimpleNamespace(
        function_call=SimpleNamespace(name="get_weather", args={"city": "London"}),
        text=None,
        thought_signature=b"london-sig",
    )
    client = MagicMock()
    client.models.generate_content_stream.side_effect = [
        iter([_google_stream_chunk(first_part)]),
        iter([_google_stream_chunk(second_part)]),
    ]
    engine = _make_cloud_engine(google_client=client)
    engine._thought_sigs = {}

    with monkeypatch.context() as patch:
        for name, module in _google_types_modules().items():
            patch.setitem(sys.modules, name, module)
        first = [
            chunk
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="Weather in Paris")],
                model="gemini-3-flash-preview",
            )
        ]
        second = [
            chunk
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="Weather in London")],
                model="gemini-3-flash-preview",
            )
        ]

    first_id = first[0].tool_calls[0]["id"]
    second_id = second[0].tool_calls[0]["id"]
    assert first_id != second_id
    assert engine._thought_sigs[first_id] == b"paris-sig"
    assert engine._thought_sigs[second_id] == b"london-sig"


@pytest.mark.asyncio
async def test_stream_full_google_emits_final_usage(monkeypatch: pytest.MonkeyPatch):
    """Google's final usage metadata is normalized onto the terminal chunk."""
    usage = SimpleNamespace(prompt_token_count=12, candidates_token_count=5)
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter(
        [
            _google_stream_chunk(text="Hello"),
            _google_stream_chunk(usage_metadata=usage),
        ]
    )
    engine = _make_cloud_engine(google_client=client)
    engine._thought_sigs = {}

    with monkeypatch.context() as patch:
        for name, module in _google_types_modules().items():
            patch.setitem(sys.modules, name, module)
        result = [
            chunk
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="hi")],
                model="gemini-2.5-flash",
            )
        ]

    assert result[-1].finish_reason == "stop"
    assert result[-1].usage == {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
    }


@pytest.mark.asyncio
async def test_stream_full_google_replays_signature_on_part(
    monkeypatch: pytest.MonkeyPatch,
):
    """A saved Gemini signature is replayed beside, not inside, function_call."""
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter([])
    engine = _make_cloud_engine(google_client=client)
    engine._thought_sigs = {"google_get_weather_0": b"sig"}
    messages = [
        Message(role=Role.USER, content="weather"),
        Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[
                ToolCall(
                    id="google_get_weather_0",
                    name="get_weather",
                    arguments='{"city": "Berlin"}',
                )
            ],
        ),
        Message(role=Role.TOOL, name="get_weather", content='{"temp": 20}'),
    ]

    with monkeypatch.context() as patch:
        for name, module in _google_types_modules().items():
            patch.setitem(sys.modules, name, module)
        result = [
            chunk
            async for chunk in engine.stream_full(
                messages, model="gemini-3-flash-preview"
            )
        ]

    contents = client.models.generate_content_stream.call_args.kwargs["contents"]
    assert contents[1]["parts"] == [
        {
            "function_call": {
                "name": "get_weather",
                "args": {"city": "Berlin"},
            },
            "thought_signature": b"sig",
        }
    ]
    assert result[-1].finish_reason == "stop"


# ---------------------------------------------------------------------------
# stream_full routing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_full_routes_to_anthropic():
    """model='claude-xxx' routes to _stream_full_anthropic."""
    msg_delta = MagicMock()
    msg_delta.stop_reason = "end_turn"
    events = [_anthropic_event("message_delta", delta=msg_delta)]
    mock_anthropic = _async_anthropic_client(events)

    engine = _make_cloud_engine(anthropic_async_client=mock_anthropic)
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
    chunks = [
        _openai_chunk(content="hi"),
        _openai_chunk(finish_reason="stop"),
    ]
    mock_client = _async_openai_client(chunks)

    engine = _make_cloud_engine(openai_async_client=mock_client)
    msgs = [Message(role=Role.USER, content="test")]

    result = []
    async for sc in engine.stream_full(msgs, model="gpt-4o"):
        result.append(sc)

    # Verify OpenAI client was used
    mock_client.chat.completions.create.assert_awaited_once()
    assert result[0].content == "hi"
    assert result[1].finish_reason == "stop"
