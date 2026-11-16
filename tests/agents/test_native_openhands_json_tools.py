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

    def __init__(self, require_confirmation=False):
        self.calls = []
        self.require_confirmation = require_confirmation

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Record arguments in memory.",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            required_capabilities=["file:write"],
            requires_confirmation=self.require_confirmation,
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


@pytest.mark.parametrize(
    ("payload", "tool_name"),
    [
        (
            '{\n"name":"unknown",\n"arguments":\nAction: counting_tool\n'
            'Action Input: {"value":"sample"}',
            "counting_tool",
        ),
        (
            '{\n"name":"unknown",\n"arguments":\n'
            "<tool_call>counting_tool\n$value=sample</tool_call>",
            "counting_tool",
        ),
        (
            '{\n"name":"unknown",\n"arguments":\n```python\nprint("sample")\n```\n}',
            "code_interpreter",
        ),
    ],
)
def test_malformed_json_objects_do_not_execute_legacy_calls_or_code(payload, tool_name):
    tool = _CountingTool()
    tool.tool_id = tool_name
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.side_effect = [{"content": payload}, {"content": "Done."}]
    instance = NativeOpenHandsAgent(engine, "test-model", tools=[tool], max_turns=2)

    result = instance.run("Show the JSON example.")

    assert tool.calls == []
    assert result.tool_results == []
    assert result.content == payload
    assert engine.generate.call_count == 1


@pytest.mark.parametrize(
    "example", ["Action: file_read", "<tool_call>file_read</tool_call>"]
)
def test_json_examples_are_preserved_in_the_final_answer(example):
    payload = json.dumps({"example": example})
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {"content": payload}
    instance = NativeOpenHandsAgent(engine, "test-model", tools=[])
    result = instance.run("Show the JSON example.")
    assert result.content == payload
    assert result.tool_results == []


def test_last_turn_json_call_reports_exhaustion_without_the_raw_envelope():
    tool = _CountingTool()
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": json.dumps({"name": tool.tool_id, "arguments": {"value": "sample"}})
    }
    instance = NativeOpenHandsAgent(engine, "test-model", tools=[tool], max_turns=1)
    result = instance.run("Record a value.")
    assert result.content.startswith("Maximum turns reached")
    assert result.metadata["max_turns_exceeded"] is True
    assert len(result.tool_results) == 1
    assert result.tool_results[0].content == "recorded"


@pytest.mark.parametrize("prefix", ["", "<think>plan</think>\n", "plan</think>\n"])
def test_json_argument_literals_survive_reasoning_cleanup(prefix):
    tool = _CountingTool()
    value = "<think>literal user data</think>"
    payload = prefix + json.dumps({"name": tool.tool_id, "arguments": {"value": value}})
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.side_effect = [{"content": payload}, {"content": "Done."}]
    instance = NativeOpenHandsAgent(engine, "test-model", tools=[tool], max_turns=2)
    instance.run("Record the literal string.")
    assert tool.calls == [{"value": value}]


@pytest.mark.parametrize(
    "payload", [json.dumps(["Action: file_read"]), json.dumps("<think>literal</think>")]
)
def test_non_object_json_answers_remain_data(payload):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {"content": payload}
    result = NativeOpenHandsAgent(engine, "test-model", tools=[]).run("Return JSON.")
    assert result.content == payload
    assert result.tool_results == []


@pytest.mark.parametrize("gate", ["confirmation", "rate_limit"])
def test_json_dispatch_keeps_confirmation_and_rate_limit_gates(gate):
    tool = _CountingTool(require_confirmation=gate == "confirmation")
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.side_effect = [
        {"content": json.dumps({"name": tool.tool_id, "arguments": {"value": "test"}})},
        {"content": "Done."},
    ]
    control = MagicMock()
    if gate == "confirmation":
        control.return_value = False
        kwargs = {"interactive": True, "confirm_callback": control}
    else:
        control.check.return_value = (False, 1.0)
        kwargs = {"rate_limiter": control}
    result = NativeOpenHandsAgent(
        engine, "test-model", tools=[tool], max_turns=2, **kwargs
    ).run("Record the value.")
    assert len(result.tool_results) == 1
    assert result.tool_results[0].success is False
    assert tool.calls == []
    assert control.called if gate == "confirmation" else control.check.called


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e400"])
def test_nonfinite_json_arguments_are_not_dispatched(agent, value):
    payload = f'{{"name":"file_read","arguments":{{"path":{value}}}}}'
    assert agent._extract_tool_call(payload) is None
