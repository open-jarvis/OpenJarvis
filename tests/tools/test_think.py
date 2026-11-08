"""Tests for the think tool."""

from __future__ import annotations

from friday_ai.tools.think import ThinkTool


class TestThinkTool:
    def test_spec(self):
        tool = ThinkTool()
        assert tool.spec.name == "think"
        assert tool.spec.category == "reasoning"
        assert tool.spec.cost_estimate == 0.0

    def test_echoes_thought(self):
        tool = ThinkTool()
        result = tool.execute(thought="Let me think step by step...")
        assert result.success is True
        assert result.content == "Let me think step by step..."

    def test_empty_thought(self):
        tool = ThinkTool()
        result = tool.execute(thought="")
        assert result.success is True
        assert result.content == ""

    def test_no_thought(self):
        tool = ThinkTool()
        result = tool.execute()
        assert result.success is True
        assert result.content == ""

    def test_openai_function(self):
        tool = ThinkTool()
        fn = tool.to_openai_function()
        assert fn["function"]["name"] == "think"
        assert "thought" in fn["function"]["parameters"]["properties"]
