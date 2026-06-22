"""Tests for the Ollama engine backend."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.ollama import OllamaEngine, _is_control_token_only_args


@pytest.fixture()
def engine() -> OllamaEngine:
    EngineRegistry.register_value("ollama", OllamaEngine)
    return OllamaEngine(host="http://testhost:11434")


class TestOllamaGenerate:
    def test_generate_returns_content(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {"role": "assistant", "content": "Hello!"},
                        "model": "qwen3:8b",
                        "prompt_eval_count": 10,
                        "eval_count": 5,
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            )
        assert result["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["usage"]["total_tokens"] == 15

    def test_generate_connection_error(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )


class TestOllamaListModels:
    def test_list_models(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                return_value=httpx.Response(
                    200,
                    json={"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}]},
                )
            )
            models = engine.list_models()
        assert models == ["qwen3:8b", "llama3.2:3b"]


class TestOllamaHealth:
    def test_health_true(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                return_value=httpx.Response(200, json={"models": []})
            )
            assert engine.health() is True

    def test_health_false(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


class TestControlTokenFilter:
    """Qwen3 ``/think`` / ``/no_think`` soft-switch tokens sometimes leak into
    tool-call arguments on small models (e.g. ``{"command": "/no_think"}``).
    Such a call is never valid and must be dropped before execution.
    """

    @pytest.mark.parametrize(
        "raw_args",
        [
            {"command": "/no_think"},
            {"command": "/think"},
            {"command": "  /no_think  "},
            {"command": "/NO_THINK"},
            "/no_think",
            json.dumps({"command": "/no_think"}),
            {"command": "/no_think", "note": ""},
        ],
    )
    def test_detects_control_token_only(self, raw_args) -> None:
        assert _is_control_token_only_args(raw_args) is True

    @pytest.mark.parametrize(
        "raw_args",
        [
            {"command": "date"},
            {"command": "echo /no_think"},
            {"query": "what is /no_think"},
            {"command": "date", "note": "/no_think"},
            {"timeout": 30},
            {},
            "date",
            "not json at all",
        ],
    )
    def test_keeps_legitimate_args(self, raw_args) -> None:
        assert _is_control_token_only_args(raw_args) is False


class TestOllamaGenerateControlToken:
    def test_generate_drops_control_token_tool_call(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "shell_exec",
                                        "arguments": {"command": "/no_think"},
                                    }
                                }
                            ],
                        },
                        "model": "qwen3:14b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="run date")],
                model="qwen3:14b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            )
        assert not result.get("tool_calls")

    def test_generate_keeps_valid_tool_call(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "shell_exec",
                                        "arguments": {"command": "date"},
                                    }
                                }
                            ],
                        },
                        "model": "qwen3:14b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="run date")],
                model="qwen3:14b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            )
        assert len(result["tool_calls"]) == 1
        assert json.loads(result["tool_calls"][0]["arguments"]) == {"command": "date"}

    def test_generate_drops_only_control_token_among_many(
        self, engine: OllamaEngine
    ) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "shell_exec",
                                        "arguments": {"command": "/no_think"},
                                    }
                                },
                                {
                                    "function": {
                                        "name": "shell_exec",
                                        "arguments": {"command": "date"},
                                    }
                                },
                            ],
                        },
                        "model": "qwen3:14b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="run date")],
                model="qwen3:14b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            )
        assert len(result["tool_calls"]) == 1
        assert json.loads(result["tool_calls"][0]["arguments"]) == {"command": "date"}


class TestOllamaStreamFullControlToken:
    @pytest.mark.asyncio
    async def test_stream_full_drops_control_token_tool_call(
        self, engine: OllamaEngine
    ) -> None:
        lines = [
            json.dumps(
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "shell_exec",
                                    "arguments": {"command": "/no_think"},
                                }
                            }
                        ],
                    },
                    "done": True,
                }
            ),
        ]
        body = "\n".join(lines)
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(200, text=body)
            )
            chunks = []
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="run date")],
                model="qwen3:14b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            ):
                chunks.append(chunk)
        assert all(not c.tool_calls for c in chunks)


class TestOllamaStream:
    @pytest.mark.asyncio
    async def test_stream_yields_content(self, engine: OllamaEngine) -> None:
        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}),
            json.dumps({"message": {"content": " world"}, "done": True}),
        ]
        body = "\n".join(lines)
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(200, text=body)
            )
            tokens = []
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            ):
                tokens.append(tok)
        assert "Hello" in tokens
