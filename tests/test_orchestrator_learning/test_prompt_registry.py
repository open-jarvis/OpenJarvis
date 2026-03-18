"""Tests for orchestrator prompt registry."""

from __future__ import annotations

from openjarvis.learning.intelligence.orchestrator.prompt_registry import (
    TOOL_DESCRIPTIONS,
    build_system_prompt,
)


class TestToolDescriptions:
    def test_calculator_present(self):
        assert "calculator" in TOOL_DESCRIPTIONS

    def test_think_present(self):
        assert "think" in TOOL_DESCRIPTIONS

    def test_each_has_category(self):
        for name, info in TOOL_DESCRIPTIONS.items():
            assert "category" in info, f"{name} missing category"

    def test_each_has_description(self):
        for name, info in TOOL_DESCRIPTIONS.items():
            assert "description" in info, f"{name} missing description"
            assert len(info["description"]) > 10


class TestBuildSystemPrompt:
    def test_includes_tool_descriptions(self):
        prompt = build_system_prompt(["calculator", "think"])
        assert "calculator" in prompt.lower()
        assert "think" in prompt.lower()

    def test_includes_response_format(self):
        prompt = build_system_prompt(["calculator"])
        assert "THOUGHT:" in prompt
        assert "TOOL:" in prompt
        assert "INPUT:" in prompt
        assert "FINAL_ANSWER:" in prompt

    def test_includes_guide_sections(self):
        prompt = build_system_prompt(
            ["calculator", "think", "code_interpreter", "web_search"]
        )
        assert "MATH PROBLEMS:" in prompt
        assert "CODING TASKS:" in prompt
        assert "REASONING/LOGIC:" in prompt

    def test_with_single_tool(self):
        prompt = build_system_prompt(["calculator"])
        assert "calculator" in prompt

    def test_default_all_tools(self):
        prompt = build_system_prompt()
        for name in TOOL_DESCRIPTIONS:
            assert name in prompt

    def test_unknown_tool_handled(self):
        prompt = build_system_prompt(["calculator", "custom_tool_xyz"])
        assert "custom_tool_xyz" in prompt

    def test_with_memory_tools(self):
        prompt = build_system_prompt(["calculator", "memory_search", "memory_store"])
        assert "memory_search" in prompt

    def test_with_llm_tool(self):
        prompt = build_system_prompt(["calculator", "llm"])
        assert "llm" in prompt.lower()
        assert "REASONING" in prompt
