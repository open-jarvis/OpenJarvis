"""Persona files reach persistent agents, not just one-shot `jarvis ask` (#376).

SOUL.md / MEMORY.md / USER.md are loaded by `jarvis ask` via SystemPromptBuilder.
Persistent agents (monitor_operative, operative) assemble their own system
prompt and previously ignored these files entirely. These tests verify the
persona is now appended to their prompt without replacing their specialized
instructions.
"""

from __future__ import annotations

from openjarvis.core.config import MemoryFilesConfig, SystemPromptConfig
from openjarvis.prompt.builder import SystemPromptBuilder


def _builder_with_soul(tmp_path, text="You are Kira."):
    soul = tmp_path / "SOUL.md"
    soul.write_text(text, encoding="utf-8")
    mf = MemoryFilesConfig(
        soul_path=str(soul),
        memory_path=str(tmp_path / "MEMORY.md"),  # absent → ignored
        user_path=str(tmp_path / "USER.md"),  # absent → ignored
    )
    return SystemPromptBuilder(
        agent_template="AGENT_TEMPLATE",
        memory_files_config=mf,
        system_prompt_config=SystemPromptConfig(),
    )


class TestPersonaSections:
    def test_persona_sections_excludes_template(self, tmp_path):
        builder = _builder_with_soul(tmp_path)
        persona = builder.persona_sections()
        assert "You are Kira." in persona
        assert "AGENT_TEMPLATE" not in persona  # template is NOT in persona

    def test_full_build_still_includes_template_and_persona(self, tmp_path):
        builder = _builder_with_soul(tmp_path)
        full = builder.build()
        assert "AGENT_TEMPLATE" in full
        assert "You are Kira." in full

    def test_persona_sections_empty_when_no_files(self, tmp_path):
        mf = MemoryFilesConfig(
            soul_path=str(tmp_path / "nope.md"),
            memory_path=str(tmp_path / "nope2.md"),
            user_path=str(tmp_path / "nope3.md"),
        )
        builder = SystemPromptBuilder(agent_template="T", memory_files_config=mf)
        assert builder.persona_sections() == ""


class TestApplyPersona:
    def test_appends_to_base_prompt(self, tmp_path):
        from openjarvis.agents.simple import SimpleAgent

        agent = SimpleAgent(object(), "m", prompt_builder=_builder_with_soul(tmp_path))
        out = agent._apply_persona("MONITOR INSTRUCTIONS")
        assert out.startswith("MONITOR INSTRUCTIONS")
        assert "You are Kira." in out

    def test_noop_without_builder(self):
        from openjarvis.agents.simple import SimpleAgent

        agent = SimpleAgent(object(), "m")
        assert agent._apply_persona("BASE") == "BASE"


class TestPersistentAgentsReceivePromptBuilder:
    """The __init__ chain must forward prompt_builder through to BaseAgent."""

    def test_monitor_operative_forwards_prompt_builder(self, tmp_path):
        from openjarvis.agents.monitor_operative import MonitorOperativeAgent

        builder = _builder_with_soul(tmp_path)
        agent = MonitorOperativeAgent(object(), "m", prompt_builder=builder)
        assert agent._prompt_builder is builder
        applied = agent._apply_persona("MONITOR INSTRUCTIONS")
        assert "MONITOR INSTRUCTIONS" in applied
        assert "You are Kira." in applied

    def test_operative_forwards_prompt_builder(self, tmp_path):
        from openjarvis.agents.operative import OperativeAgent

        builder = _builder_with_soul(tmp_path)
        agent = OperativeAgent(object(), "m", prompt_builder=builder)
        assert agent._prompt_builder is builder
        assert "You are Kira." in agent._apply_persona("OP INSTRUCTIONS")

    def test_monitor_operative_without_builder_is_unaffected(self):
        from openjarvis.agents.monitor_operative import MonitorOperativeAgent

        agent = MonitorOperativeAgent(object(), "m")
        assert agent._prompt_builder is None
        assert agent._apply_persona("BASE") == "BASE"
