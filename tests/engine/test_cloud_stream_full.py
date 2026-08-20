"""Tests for CloudEngine.stream_full, _stream_full_openai, _stream_full_anthropic,
and _prepare_anthropic_messages."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
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
