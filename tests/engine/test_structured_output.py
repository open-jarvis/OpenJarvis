"""Tests for structured output / JSON mode across engines."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import ResponseFormat
from openjarvis.engine.cloud import CloudEngine
from openjarvis.engine.ollama import OllamaEngine

# ---------------------------------------------------------------------------
# ResponseFormat dataclass
# ---------------------------------------------------------------------------


class TestResponseFormat:
    def test_default_type(self) -> None:
        rf = ResponseFormat()
        assert rf.type == "json_object"
        assert rf.schema is None

    def test_json_schema_type(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        rf = ResponseFormat(type="json_schema", schema=schema)
        assert rf.type == "json_schema"
        assert rf.schema == schema

    def test_slots(self) -> None:
        rf = ResponseFormat()
        with pytest.raises(AttributeError):
            rf.extra = "nope"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Cloud engine — OpenAI
# ---------------------------------------------------------------------------


class TestOpenAIStructuredOutput:
    def _make_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[CloudEngine, mock.MagicMock]:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        fake_client = mock.MagicMock()
        engine._openai_client = fake_client

        fake_usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )
        fake_choice = SimpleNamespace(
            message=SimpleNamespace(content='{"answer": 42}', tool_calls=None),
            finish_reason="stop",
        )
        fake_resp = SimpleNamespace(
            choices=[fake_choice], usage=fake_usage, model="gpt-4o"
        )
        fake_client.chat.completions.create.return_value = fake_resp
        return engine, fake_client

    def test_json_object_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        rf = ResponseFormat()
        engine.generate(
            [Message(role=Role.USER, content="Give me JSON")],
            model="gpt-4o",
            response_format=rf,
        )
        call_kwargs = fake_client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_json_schema_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        rf = ResponseFormat(type="json_schema", schema=schema)
        engine.generate(
            [Message(role=Role.USER, content="Give me JSON")],
            model="gpt-4o",
            response_format=rf,
        )
        call_kwargs = fake_client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"]["type"] == "json_schema"
        assert call_kwargs["response_format"]["json_schema"]["name"] == "response"
        assert call_kwargs["response_format"]["json_schema"]["schema"] == schema

    def test_raw_dict_passthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        raw = {"type": "json_object"}
        engine.generate(
            [Message(role=Role.USER, content="Give me JSON")],
            model="gpt-4o",
            response_format=raw,
        )
        call_kwargs = fake_client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == raw

    def test_no_response_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        engine.generate(
            [Message(role=Role.USER, content="Hi")],
            model="gpt-4o",
        )
        call_kwargs = fake_client.chat.completions.create.call_args[1]
        assert "response_format" not in call_kwargs


# ---------------------------------------------------------------------------
# Cloud engine — Anthropic
# ---------------------------------------------------------------------------


class TestAnthropicStructuredOutput:
    def _make_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[CloudEngine, mock.MagicMock]:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        fake_client = mock.MagicMock()
        engine._anthropic_client = fake_client

        fake_usage = SimpleNamespace(input_tokens=12, output_tokens=8)
        fake_tool_use = SimpleNamespace(
            type="tool_use",
            id="tool_123",
            name="json_output",
            input={"answer": 42},
        )
        fake_resp = SimpleNamespace(
            content=[fake_tool_use],
            usage=fake_usage,
            model="claude-sonnet-4-20250514",
            stop_reason="tool_use",
        )
        fake_client.messages.create.return_value = fake_resp
        return engine, fake_client

    def test_json_mode_uses_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        rf = ResponseFormat()
        engine.generate(
            [Message(role=Role.USER, content="Give me JSON")],
            model="claude-sonnet-4-20250514",
            response_format=rf,
        )
        call_kwargs = fake_client.messages.create.call_args[1]
        # Should have a tools list with the json_output tool
        assert "tools" in call_kwargs
        tool_names = [t["name"] for t in call_kwargs["tools"]]
        assert "json_output" in tool_names
        # Should force the tool via tool_choice
        assert call_kwargs["tool_choice"] == {
            "type": "tool",
            "name": "json_output",
        }

    def test_json_schema_uses_custom_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        rf = ResponseFormat(type="json_schema", schema=schema)
        engine.generate(
            [Message(role=Role.USER, content="Give me JSON")],
            model="claude-sonnet-4-20250514",
            response_format=rf,
        )
        call_kwargs = fake_client.messages.create.call_args[1]
        json_tool = [t for t in call_kwargs["tools"] if t["name"] == "json_output"][0]
        assert json_tool["input_schema"] == schema

    def test_appends_to_existing_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        rf = ResponseFormat()
        existing_tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web",
                    "parameters": {"type": "object"},
                },
            }
        ]
        engine.generate(
            [Message(role=Role.USER, content="Give me JSON")],
            model="claude-sonnet-4-20250514",
            response_format=rf,
            tools=existing_tools,
        )
        call_kwargs = fake_client.messages.create.call_args[1]
        tool_names = [t["name"] for t in call_kwargs["tools"]]
        assert "search" in tool_names
        assert "json_output" in tool_names


# ---------------------------------------------------------------------------
# Cloud engine — Google
# ---------------------------------------------------------------------------


class TestGoogleStructuredOutput:
    def _make_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[CloudEngine, mock.MagicMock]:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        EngineRegistry.register_value("cloud", CloudEngine)
        engine = CloudEngine()
        fake_client = mock.MagicMock()
        engine._google_client = fake_client

        fake_part = SimpleNamespace(
            text='{"answer": 42}',
            function_call=None,
        )
        fake_candidate = SimpleNamespace(content=SimpleNamespace(parts=[fake_part]))
        fake_um = SimpleNamespace(prompt_token_count=10, candidates_token_count=5)
        fake_resp = SimpleNamespace(
            candidates=[fake_candidate],
            usage_metadata=fake_um,
            text='{"answer": 42}',
        )
        fake_client.models.generate_content.return_value = fake_resp
        return engine, fake_client

    def test_json_mode_sets_mime_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        rf = ResponseFormat()

        # Patch the genai_types import used inside _generate_google
        fake_config_cls = mock.MagicMock()
        config_instance = mock.MagicMock()
        fake_config_cls.return_value = config_instance
        fake_genai_types = mock.MagicMock()
        fake_genai_types.GenerateContentConfig = fake_config_cls

        with mock.patch.dict(
            "sys.modules",
            {"google": mock.MagicMock(), "google.genai": mock.MagicMock()},
        ):
            with mock.patch(
                "openjarvis.engine.cloud.genai_types", fake_genai_types, create=True
            ):
                # We need to actually test the config mutation. The simplest
                # approach is to observe the config object passed to
                # generate_content.
                engine.generate(
                    [Message(role=Role.USER, content="Give me JSON")],
                    model="gemini-2.5-pro",
                    response_format=rf,
                )

        call_kwargs = fake_client.models.generate_content.call_args
        config_arg = call_kwargs[1]["config"]
        assert config_arg.response_mime_type == "application/json"

    def test_json_schema_sets_response_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine, fake_client = self._make_engine(monkeypatch)
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        rf = ResponseFormat(type="json_schema", schema=schema)

        with mock.patch.dict(
            "sys.modules",
            {"google": mock.MagicMock(), "google.genai": mock.MagicMock()},
        ):
            engine.generate(
                [Message(role=Role.USER, content="Give me JSON")],
                model="gemini-2.5-pro",
                response_format=rf,
            )

        call_kwargs = fake_client.models.generate_content.call_args
        config_arg = call_kwargs[1]["config"]
        assert config_arg.response_mime_type == "application/json"
        assert config_arg.response_schema == schema


# ---------------------------------------------------------------------------
# Ollama engine
# ---------------------------------------------------------------------------


class TestOllamaStructuredOutput:
    @pytest.fixture()
    def engine(self) -> OllamaEngine:
        EngineRegistry.register_value("ollama", OllamaEngine)
        return OllamaEngine(host="http://testhost:11434")

    def test_json_format_in_payload(self, engine: OllamaEngine) -> None:
        rf = ResponseFormat()
        with respx.mock:
            route = respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": '{"answer": 42}',
                        },
                        "model": "qwen3:8b",
                        "prompt_eval_count": 10,
                        "eval_count": 5,
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Give me JSON")],
                model="qwen3:8b",
                response_format=rf,
            )
            # Verify the payload sent to Ollama
            sent_payload = json.loads(route.calls[0].request.content)
            assert sent_payload["format"] == "json"

        assert result["content"] == '{"answer": 42}'

    def test_raw_dict_format_in_payload(self, engine: OllamaEngine) -> None:
        with respx.mock:
            route = respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": '{"answer": 42}',
                        },
                        "model": "qwen3:8b",
                        "prompt_eval_count": 10,
                        "eval_count": 5,
                    },
                )
            )
            engine.generate(
                [Message(role=Role.USER, content="Give me JSON")],
                model="qwen3:8b",
                response_format={"type": "json_object"},
            )
            sent_payload = json.loads(route.calls[0].request.content)
            assert sent_payload["format"] == "json"

    def test_no_format_without_response_format(self, engine: OllamaEngine) -> None:
        with respx.mock:
            route = respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "Hello!",
                        },
                        "model": "qwen3:8b",
                        "prompt_eval_count": 10,
                        "eval_count": 5,
                    },
                )
            )
            engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model="qwen3:8b",
            )
            sent_payload = json.loads(route.calls[0].request.content)
            assert "format" not in sent_payload
