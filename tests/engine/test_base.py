from __future__ import annotations

from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.engine._base import estimate_prompt_tokens


def test_estimate_prompt_tokens_handles_none_content_tool_call_turn() -> None:
    messages = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[ToolCall(id="call_1", name="lookup", arguments="{}")],
        ),
    ]

    assert estimate_prompt_tokens(messages) == 12


def test_estimate_prompt_tokens_counts_tool_call_arguments() -> None:
    base = [
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, content=None),
    ]
    with_tool_call = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[ToolCall(id="", name="", arguments="abcdefgh")],
        ),
    ]

    assert estimate_prompt_tokens(with_tool_call) - estimate_prompt_tokens(base) == 2


def test_estimate_prompt_tokens_counts_reasoning_metadata() -> None:
    base = [
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, content=None),
    ]
    with_reasoning = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=None,
            metadata={"reasoning_content": "abcdefgh"},
        ),
    ]

    assert estimate_prompt_tokens(with_reasoning) - estimate_prompt_tokens(base) == 2


def test_estimate_prompt_tokens_counts_tool_result_ids() -> None:
    messages = [
        Message(role=Role.USER, content="hi"),
        Message(role=Role.TOOL, content="ok", tool_call_id="abcdefgh"),
    ]

    assert estimate_prompt_tokens(messages) == 11
