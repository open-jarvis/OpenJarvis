"""Tests for SystemPromptBuilder skill few-shot injection (Plan 2A)."""

from __future__ import annotations

from openjarvis.prompt.builder import SystemPromptBuilder


class TestSystemPromptBuilderFewShot:
    def test_no_few_shot_no_section(self):
        builder = SystemPromptBuilder(
            agent_template="You are an agent.",
        )
        prompt = builder.build()
        assert "## Skill Examples" not in prompt

    def test_few_shot_section_appears_in_prompt(self):
        builder = SystemPromptBuilder(
            agent_template="You are an agent.",
            skill_few_shot_examples=[
                "### research-skill\nInput: q1\nOutput: a1",
                "### code-skill\nInput: q2\nOutput: a2",
            ],
        )
        prompt = builder.build()
        assert "## Skill Examples" in prompt
        assert "research-skill" in prompt
        assert "code-skill" in prompt
        assert "Input: q1" in prompt
        assert "Output: a2" in prompt

    def test_empty_few_shot_list_no_section(self):
        builder = SystemPromptBuilder(
            agent_template="You are an agent.",
            skill_few_shot_examples=[],
        )
        prompt = builder.build()
        assert "## Skill Examples" not in prompt
