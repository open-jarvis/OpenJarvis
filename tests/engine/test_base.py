from __future__ import annotations

from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.engine._base import estimate_prompt_tokens


def test_estimate_prompt_tokens_handles_none_content_tool_call_turn() -> None:
    messages = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=None,  # type: ignore[arg-type]
            tool_calls=[ToolCall(id="call_1", name="lookup", arguments="{}")],
        ),
    ]

    assert estimate_prompt_tokens(messages) == 8
