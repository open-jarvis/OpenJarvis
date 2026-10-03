"""Regression tests for the non-streaming cloud tool-call contract (#1088)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import CloudEngine


@pytest.fixture(params=["openai", "openrouter", "atlascloud"])
def cloud_engine(request: pytest.FixtureRequest) -> tuple[CloudEngine, MagicMock, str]:
    """Use real adapters with a mocked SDK transport, never a live API."""
    provider = request.param
    engine = CloudEngine()
    client = MagicMock()
    setattr(engine, f"_{provider}_client", client)
    model = "gpt-4o" if provider == "openai" else f"{provider}/openai/gpt-4o"
    return engine, client, model


def _response(message: SimpleNamespace, *, finish_reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        model="openai/gpt-4o",
    )


def _tool_calls(count: int) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=f"call_{i}",
            type="function",
            function=SimpleNamespace(
                name="calculator", arguments=f'{{"expression": "{i + 2}**2"}}'
            ),
        )
        for i in range(count)
    ]


@pytest.mark.parametrize("count", [1, 2])
def test_generate_returns_flat_tool_calls(
    cloud_engine: tuple[CloudEngine, MagicMock, str], count: int
) -> None:
    engine, client, model = cloud_engine
    calls = _tool_calls(count)
    client.chat.completions.create.return_value = _response(
        SimpleNamespace(content=None, tool_calls=calls), finish_reason="tool_calls"
    )
    tools = [{"type": "function", "function": {"name": "calculator"}}]

    result = engine.generate(
        [Message(role=Role.USER, content="Calculate squares")],
        model=model,
        tools=tools,
        tool_choice="auto",
    )

    assert result["tool_calls"] == [
        {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
        for tc in calls
    ]
    assert result["content"] == ""
    assert result["finish_reason"] == "tool_calls"
    assert result["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    sent = client.chat.completions.create.call_args.kwargs
    assert sent["tools"] == tools
    assert sent["tool_choice"] == "auto"


@pytest.mark.parametrize("state", ["missing", "null", "empty"])
def test_generate_without_tool_calls(
    cloud_engine: tuple[CloudEngine, MagicMock, str], state: str
) -> None:
    engine, client, model = cloud_engine
    message = SimpleNamespace(content="No tool needed")
    if state != "missing":
        message.tool_calls = None if state == "null" else []
    client.chat.completions.create.return_value = _response(
        message, finish_reason="stop"
    )

    result = engine.generate([Message(role=Role.USER, content="Hi")], model=model)

    assert "tool_calls" not in result
    assert result["content"] == "No tool needed"
    assert result["finish_reason"] == "stop"


def test_orchestrator_dispatches_cloud_tools_and_preserves_reply_ids(
    cloud_engine: tuple[CloudEngine, MagicMock, str],
) -> None:
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.tools.calculator import CalculatorTool

    engine, client, model = cloud_engine
    calls = _tool_calls(2)
    client.chat.completions.create.side_effect = [
        _response(
            SimpleNamespace(content=None, tool_calls=calls), finish_reason="tool_calls"
        ),
        _response(
            SimpleNamespace(content="4 and 9", tool_calls=[]), finish_reason="stop"
        ),
    ]
    agent = OrchestratorAgent(engine, model, tools=[CalculatorTool()], max_turns=2)

    result = agent.run("Calculate 2**2 and 3**2")

    assert result.content == "4 and 9"
    assert result.turns == 2
    assert len(result.tool_results) == 2
    assert all(
        tr.success and tr.tool_name == "calculator" for tr in result.tool_results
    )
    assert [tr.content for tr in result.tool_results] == ["4.0", "9.0"]
    assert client.chat.completions.create.call_count == 2
    messages = client.chat.completions.create.call_args.kwargs["messages"]
    replies = [msg for msg in messages if msg["role"] == "tool"]
    assert [(msg["tool_call_id"], msg["content"]) for msg in replies] == [
        ("call_0", "4.0"),
        ("call_1", "9.0"),
    ]
    assistant = next(msg for msg in messages if msg.get("tool_calls"))
    assert assistant["tool_calls"] == [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        }
        for tc in calls
    ]


def test_http_response_mapping_preserves_openai_wire_format(
    cloud_engine: tuple[CloudEngine, MagicMock, str],
) -> None:
    pytest.importorskip("fastapi")
    from openjarvis.server.models import ChatCompletionRequest
    from openjarvis.server.routes import _handle_direct

    engine, client, model = cloud_engine
    calls = _tool_calls(2)
    client.chat.completions.create.return_value = _response(
        SimpleNamespace(content=None, tool_calls=calls), finish_reason="tool_calls"
    )
    request = ChatCompletionRequest(
        model=model, messages=[{"role": "user", "content": "Calculate squares"}]
    )

    response = _handle_direct(engine, model, request).model_dump()

    assert response["choices"][0]["finish_reason"] == "tool_calls"
    assert response["choices"][0]["message"]["tool_calls"] == [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        }
        for tc in calls
    ]
