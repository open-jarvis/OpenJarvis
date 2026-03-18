"""Tests for tool_calls extraction in _OpenAICompatibleEngine and OllamaEngine."""

from __future__ import annotations

import json

import httpx

from openjarvis.core.types import Message, Role
from openjarvis.engine._openai_compat import _OpenAICompatibleEngine
from openjarvis.engine.ollama import OllamaEngine

# ---------------------------------------------------------------------------
# _OpenAICompatibleEngine tests
# ---------------------------------------------------------------------------


class _TestEngine(_OpenAICompatibleEngine):
    engine_id = "test"
    _default_host = "http://localhost:9999"


class TestOpenAICompatToolCalls:
    def test_no_tool_calls(self, respx_mock):
        """When no tool_calls in response, result has no tool_calls key."""
        respx_mock.post("http://localhost:9999/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "Hi"}, "finish_reason": "stop"},
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 2,
                        "total_tokens": 7,
                    },
                    "model": "test",
                },
            )
        )
        engine = _TestEngine()
        result = engine.generate(
            [Message(role=Role.USER, content="Hello")],
            model="test",
        )
        assert "tool_calls" not in result
        assert result["content"] == "Hi"

    def test_with_tool_calls(self, respx_mock):
        """Extract tool_calls from OpenAI-format response."""
        respx_mock.post("http://localhost:9999/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_abc",
                                        "type": "function",
                                        "function": {
                                            "name": "calculator",
                                            "arguments": '{"expression":"2+2"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 10,
                        "total_tokens": 15,
                    },
                    "model": "test",
                },
            )
        )
        engine = _TestEngine()
        result = engine.generate(
            [Message(role=Role.USER, content="Calculate 2+2")],
            model="test",
        )
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "call_abc"
        assert tc["name"] == "calculator"
        assert tc["arguments"] == '{"expression":"2+2"}'
        assert result["content"] == ""  # None → ""

    def test_tools_kwarg_passthrough(self, respx_mock):
        """Tools kwarg is spread into the payload via **kwargs."""
        captured = {}

        def capture(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "ok"}, "finish_reason": "stop"}
                    ],
                    "usage": {},
                    "model": "test",
                },
            )

        respx_mock.post("http://localhost:9999/v1/chat/completions").mock(
            side_effect=capture,
        )
        engine = _TestEngine()
        engine.generate(
            [Message(role=Role.USER, content="Hello")],
            model="test",
            tools=[{"type": "function", "function": {"name": "calc"}}],
        )
        assert "tools" in captured["body"]

    def test_multiple_tool_calls(self, respx_mock):
        respx_mock.post("http://localhost:9999/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {"name": "a", "arguments": "{}"},
                                    },
                                    {
                                        "id": "c2",
                                        "type": "function",
                                        "function": {"name": "b", "arguments": "{}"},
                                    },
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {},
                    "model": "test",
                },
            )
        )
        engine = _TestEngine()
        result = engine.generate(
            [Message(role=Role.USER, content="Use tools")],
            model="test",
        )
        assert len(result["tool_calls"]) == 2


# ---------------------------------------------------------------------------
# OllamaEngine tests
# ---------------------------------------------------------------------------


class TestOllamaToolCalls:
    def test_no_tool_calls(self, respx_mock):
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "message": {"content": "Hi"},
                    "model": "test",
                    "prompt_eval_count": 5,
                    "eval_count": 2,
                },
            )
        )
        engine = OllamaEngine()
        result = engine.generate(
            [Message(role=Role.USER, content="Hello")],
            model="test",
        )
        assert "tool_calls" not in result

    def test_with_tool_calls(self, respx_mock):
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"expression":"3*3"}',
                                },
                            }
                        ],
                    },
                    "model": "test",
                    "prompt_eval_count": 5,
                    "eval_count": 3,
                },
            )
        )
        engine = OllamaEngine()
        result = engine.generate(
            [Message(role=Role.USER, content="3*3")],
            model="test",
        )
        assert "tool_calls" in result
        assert result["tool_calls"][0]["name"] == "calculator"

    def test_tools_in_payload(self, respx_mock):
        captured = {}

        def capture(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "message": {"content": "ok"},
                    "model": "test",
                },
            )

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=capture)
        engine = OllamaEngine()
        engine.generate(
            [Message(role=Role.USER, content="Hello")],
            model="test",
            tools=[{"type": "function", "function": {"name": "calc"}}],
        )
        assert "tools" in captured["body"]

    def test_dict_arguments_serialized_to_json(self, respx_mock):
        """Ollama returns arguments as dict — engine must serialize."""
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "calculator",
                                    "arguments": {"expression": "3*3"},
                                },
                            }
                        ],
                    },
                    "model": "test",
                    "prompt_eval_count": 5,
                    "eval_count": 3,
                },
            )
        )
        engine = OllamaEngine()
        result = engine.generate(
            [Message(role=Role.USER, content="3*3")],
            model="test",
        )
        assert "tool_calls" in result
        tc = result["tool_calls"][0]
        assert isinstance(tc["arguments"], str)
        assert json.loads(tc["arguments"]) == {
            "expression": "3*3",
        }

    def test_no_tools_no_tools_key(self, respx_mock):
        captured = {}

        def capture(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "message": {"content": "ok"},
                    "model": "test",
                },
            )

        respx_mock.post("http://localhost:11434/api/chat").mock(side_effect=capture)
        engine = OllamaEngine()
        engine.generate(
            [Message(role=Role.USER, content="Hello")],
            model="test",
        )
        assert "tools" not in captured["body"]
