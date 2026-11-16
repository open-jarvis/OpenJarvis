"""Regression tests for JSON-formatted tool calls from local models."""

import json
from unittest.mock import Mock

import pytest

from openjarvis.agents.native_openhands import NativeOpenHandsAgent


@pytest.fixture
def agent():
    """Create a parser-only agent without loading an LLM."""
    instance = NativeOpenHandsAgent.__new__(NativeOpenHandsAgent)

    instance._executor = Mock()
    instance._executor.get_openai_tools.return_value = [
        {"type": "function", "function": {"name": "file_write"}},
        {"type": "function", "function": {"name": "file_read"}},
    ]
    return instance


def test_valid_json_tool_call(agent):
    response = json.dumps({
        "name": "file_write",
        "arguments": {
            "path": "/tmp/hello.txt",
            "content": "Hello from Qwen",
        },
    })

    result = agent._extract_tool_call(response)

    assert result is not None
    name, arguments = result
    assert name == "file_write"
    assert json.loads(arguments) == {
        "path": "/tmp/hello.txt",
        "content": "Hello from Qwen",
    }


def test_unknown_tool_is_rejected(agent):
    response = json.dumps({
        "name": "unknown_tool",
        "arguments": {"command": "echo hello"},
    })

    assert agent._extract_tool_call(response) is None


@pytest.mark.parametrize("response", [
    '{"name": "file_write", "arguments":',
    '{"name": "file_write", "arguments": []}',
    '{"name": "file_write"}',
    '{"name": 123, "arguments": {}}',
    '[]',
    'This is an ordinary assistant response.',
])
def test_invalid_json_is_not_executed(agent, response):
    assert agent._extract_tool_call(response) is None


def test_action_format_still_works(agent):
    response = (
        'Action: file_write\n'
        'Action Input: {"path": "/tmp/hello.txt", "content": "Hi"}'
    )

    name, arguments = agent._extract_tool_call(response)

    assert name == "file_write"
    assert json.loads(arguments)["content"] == "Hi"


def test_xml_format_still_works(agent):
    response = (
        "<tool_call>file_read\n"
        "$path=/tmp/hello.txt\n"
        "</tool_call>"
    )

    name, arguments = agent._extract_tool_call(response)

    assert name == "file_read"
    assert json.loads(arguments)["path"] == "/tmp/hello.txt"


def test_json_with_whitespace(agent):
    response = '''
    {
        "name": "file_read",
        "arguments": {"path": "/tmp/hello.txt"}
    }
    '''

    name, arguments = agent._extract_tool_call(response)

    assert name == "file_read"
    assert json.loads(arguments)["path"] == "/tmp/hello.txt"
