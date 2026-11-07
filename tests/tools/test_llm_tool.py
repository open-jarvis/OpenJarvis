"""Tests for the LLM tool."""

from __future__ import annotations

from unittest.mock import MagicMock

from friday_ai.tools.llm_tool import LLMTool


def _make_mock_engine(content: str = "response") -> MagicMock:
    engine = MagicMock()
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return engine


class TestLLMTool:
    def test_spec(self):
        tool = LLMTool()
        assert tool.spec.name == "llm"
        assert tool.spec.category == "inference"

    def test_no_engine(self):
        tool = LLMTool()
        result = tool.execute(prompt="hello")
        assert result.success is False
        assert "No inference engine" in result.content

    def test_no_model(self):
        tool = LLMTool(engine=_make_mock_engine(), model="")
        result = tool.execute(prompt="hello")
        assert result.success is False
        assert "No model" in result.content

    def test_no_prompt(self):
        tool = LLMTool(engine=_make_mock_engine(), model="test-model")
        result = tool.execute(prompt="")
        assert result.success is False

    def test_successful_generation(self):
        engine = _make_mock_engine("The answer is 42.")
        tool = LLMTool(engine=engine, model="test-model")
        result = tool.execute(prompt="What is the answer?")
        assert result.success is True
        assert result.content == "The answer is 42."
        assert result.usage["total_tokens"] == 15
        engine.generate.assert_called_once()

    def test_with_system_message(self):
        engine = _make_mock_engine()
        tool = LLMTool(engine=engine, model="test-model")
        tool.execute(prompt="hello", system="You are helpful.")
        call_args = engine.generate.call_args
        messages = call_args[0][0]
        assert len(messages) == 2
        assert messages[0].role.value == "system"
        assert messages[1].role.value == "user"

    def test_engine_error(self):
        engine = MagicMock()
        engine.generate.side_effect = RuntimeError("connection failed")
        tool = LLMTool(engine=engine, model="test-model")
        result = tool.execute(prompt="hello")
        assert result.success is False
        assert "LLM error" in result.content
