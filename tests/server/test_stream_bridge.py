"""Regression tests for streaming completed agent responses."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from openjarvis.agents._stubs import AgentResult  # noqa: E402
from openjarvis.core.events import EventBus  # noqa: E402
from openjarvis.core.types import ToolResult  # noqa: E402
from openjarvis.server.models import ChatCompletionRequest  # noqa: E402
from openjarvis.server.stream_bridge import AgentStreamBridge  # noqa: E402


def _streamed_content(events: list[str]) -> str:
    """Join assistant content from OpenAI-compatible data chunks."""
    content = []
    for event in events:
        if not event.startswith("data: {"):
            continue
        payload = json.loads(event.removeprefix("data: ").strip())
        choices = payload.get("choices")
        if choices and choices[0]["delta"].get("content"):
            content.append(choices[0]["delta"]["content"])
    return "".join(content)


def test_stream_replays_grounded_agent_result_without_second_inference():
    grounded_content = "My name is Jarvis. The tool reports 72 degrees."
    agent = MagicMock()
    agent._model = "configured-model"
    agent.run.return_value = AgentResult(
        content=grounded_content,
        tool_results=[
            ToolResult(tool_name="weather", content="72 degrees", success=True)
        ],
        metadata={"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
    )

    async def ungrounded_replay(*args, **kwargs):
        raise AssertionError("stream_full must not run after agent.run")
        yield  # pragma: no cover

    agent._engine.stream_full = ungrounded_replay
    request = ChatCompletionRequest(
        model="requested-model",
        messages=[{"role": "user", "content": "Who are you, and what's outside?"}],
        stream=True,
    )
    bridge = AgentStreamBridge(agent, EventBus(), request.model, request)

    async def collect_events() -> list[str]:
        return [event async for event in bridge.stream()]

    events = asyncio.run(collect_events())

    assert _streamed_content(events) == grounded_content
    assert any(event.startswith("event: tool_results\n") for event in events)
    agent.run.assert_called_once()
    assert agent._model == "configured-model"


def test_tool_call_start_serializes_arguments_for_sse_without_mutating_event():
    bridge = object.__new__(AgentStreamBridge)
    event_data = {
        "tool": "web_search",
        "arguments": {"query": "python"},
        "agent": "agent-1",
    }

    event = bridge._format_named_event("tool_call_start", event_data)
    payload = json.loads(event.split("data: ", 1)[1])

    assert payload["arguments"] == '{"query": "python"}'
    assert event_data["arguments"] == {"query": "python"}


def test_tool_call_start_preserves_already_serialized_arguments():
    bridge = object.__new__(AgentStreamBridge)

    event = bridge._format_named_event(
        "tool_call_start",
        {"tool": "web_search", "arguments": '{"query":"python"}'},
    )
    payload = json.loads(event.split("data: ", 1)[1])

    assert payload["arguments"] == '{"query":"python"}'
