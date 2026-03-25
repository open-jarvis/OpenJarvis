"""Tests for VLLMEngine._fix_tool_call_arguments."""

from __future__ import annotations

import json

from openjarvis.engine.openai_compat_engines import VLLMEngine


def test_fix_dict_to_string():
    """Dict arguments are serialized to JSON string."""
    msg_dicts = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "Berlin", "units": "metric"},
                    },
                }
            ],
        }
    ]

    result = VLLMEngine._fix_tool_call_arguments(msg_dicts)
    args = result[0]["tool_calls"][0]["function"]["arguments"]
    assert isinstance(args, str)
    assert json.loads(args) == {"city": "Berlin", "units": "metric"}


def test_fix_string_passthrough():
    """String arguments are left as-is."""
    msg_dicts = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "calc",
                        "arguments": '{"x": 42}',
                    },
                }
            ],
        }
    ]

    result = VLLMEngine._fix_tool_call_arguments(msg_dicts)
    args = result[0]["tool_calls"][0]["function"]["arguments"]
    assert args == '{"x": 42}'


def test_fix_no_tool_calls():
    """Messages without tool_calls are unchanged."""
    msg_dicts = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    original = [dict(m) for m in msg_dicts]

    result = VLLMEngine._fix_tool_call_arguments(msg_dicts)
    assert result == original
