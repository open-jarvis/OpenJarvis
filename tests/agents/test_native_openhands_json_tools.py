"""Regression tests for JSON-formatted tool calls from local models."""

import json
from unittest.mock import MagicMock, Mock

import pytest

from openjarvis.agents.native_openhands import NativeOpenHandsAgent
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


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
    response = json.dumps(
        {
            "name": "file_write",
            "arguments": {
                "path": "/tmp/hello.txt",
                "content": "Hello from Qwen",
            },
        }
    )

    result = agent._extract_tool_call(response)

    assert result is not None
    name, arguments = result
    assert name == "file_write"
    assert json.loads(arguments) == {
        "path": "/tmp/hello.txt",
        "content": "Hello from Qwen",
    }


def test_unknown_tool_is_rejected(agent):
    response = json.dumps(
        {
            "name": "unknown_tool",
            "arguments": {"command": "echo hello"},
        }
    )

    assert agent._extract_tool_call(response) is None


@pytest.mark.parametrize(
    "response",
    [
        '{"name": "file_write", "arguments":',
        '{"name": "file_write", "arguments": []}',
        '{"name": "file_write"}',
        '{"name": 123, "arguments": {}}',
        "[]",
        "This is an ordinary assistant response.",
    ],
)
def test_invalid_json_is_not_executed(agent, response):
    assert agent._extract_tool_call(response) is None


def test_action_format_still_works(agent):
    response = (
        'Action: file_write\nAction Input: {"path": "/tmp/hello.txt", "content": "Hi"}'
    )

    name, arguments = agent._extract_tool_call(response)

    assert name == "file_write"
    assert json.loads(arguments)["content"] == "Hi"


def test_xml_format_still_works(agent):
    response = "<tool_call>file_read\n$path=/tmp/hello.txt\n</tool_call>"

    name, arguments = agent._extract_tool_call(response)

    assert name == "file_read"
    assert json.loads(arguments)["path"] == "/tmp/hello.txt"


def test_json_with_whitespace(agent):
    response = """
    {
        "name": "file_read",
        "arguments": {"path": "/tmp/hello.txt"}
    }
    """

    name, arguments = agent._extract_tool_call(response)

    assert name == "file_read"
    assert json.loads(arguments)["path"] == "/tmp/hello.txt"


def test_unrelated_json_is_not_reparsed_as_action_text(agent):
    response = json.dumps({"example": "Action: file_read", "arguments": {}})
    assert agent._extract_tool_call(response) is None


class _CountingTool(BaseTool):
    tool_id = "counting_tool"

    def __init__(self):
        self.calls = []

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Record arguments in memory.",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            required_capabilities=["file:write"],
        )

    def execute(self, **params):
        self.calls.append(params)
        return ToolResult(tool_name=self.tool_id, content="recorded", success=True)


@pytest.mark.parametrize("denied", [False, True])
def test_json_calls_use_the_secured_executor(denied):
    tool = _CountingTool()
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.side_effect = [
        {"content": json.dumps({"name": tool.tool_id, "arguments": {"value": "test"}})},
        {"content": "Done."},
    ]
    policy = MagicMock()
    policy.check.return_value = not denied
    instance = NativeOpenHandsAgent(
        engine, "test-model", tools=[tool], max_turns=2, capability_policy=policy
    )

    result = instance.run("Record a value.")

    assert result.content == "Done."
    assert len(result.tool_results) == 1
    assert result.tool_results[0].success is not denied
    assert tool.calls == ([] if denied else [{"value": "test"}])
    assert policy.check.called
