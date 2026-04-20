"""Tests for native_react skill_few_shot_examples wiring (Plan 2B I3 fix)."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents.native_react import REACT_SYSTEM_PROMPT, NativeReActAgent


class _StubEngine:
    def generate(self, *args, **kwargs):
        return {"content": "Final Answer: stub", "usage": {}}


class TestToolUsingAgentAcceptsKwarg:
    def test_default_empty_list(self):
        agent = NativeReActAgent(
            engine=_StubEngine(),
            model="stub",
            tools=[],
        )
        assert agent._skill_few_shot_examples == []

    def test_explicit_examples_stored(self):
        examples = ["### research-skill\nInput: q\nOutput: a"]
        agent = NativeReActAgent(
            engine=_StubEngine(),
            model="stub",
            tools=[],
            skill_few_shot_examples=examples,
        )
        assert agent._skill_few_shot_examples == examples

    def test_none_resolves_to_empty_list(self):
        agent = NativeReActAgent(
            engine=_StubEngine(),
            model="stub",
            tools=[],
            skill_few_shot_examples=None,
        )
        assert agent._skill_few_shot_examples == []


class TestReactSystemPromptPlaceholder:
    def test_format_with_empty_examples(self):
        rendered = REACT_SYSTEM_PROMPT.format(
            tool_descriptions="No tools available.",
            skill_examples="",
        )
        assert "## Skill Examples" not in rendered
        assert "No tools available." in rendered
        # ReAct format spec must still be present
        assert "Thought:" in rendered
        assert "Action:" in rendered
        assert "Final Answer:" in rendered

    def test_format_with_non_empty_examples(self):
        examples_block = (
            "## Skill Examples\n\n### research-skill\nInput: q\nOutput: a\n\n"
        )
        rendered = REACT_SYSTEM_PROMPT.format(
            tool_descriptions="No tools available.",
            skill_examples=examples_block,
        )
        assert "## Skill Examples" in rendered
        assert "research-skill" in rendered
        assert "Input: q" in rendered
        assert "Output: a" in rendered


class TestSystemBuilderCapturesFewShot:
    def test_skill_manager_examples_stored_on_system(self, tmp_path):
        """SystemBuilder.build() pulls examples from SkillManager and
        stashes them on the JarvisSystem instance for _run_agent to
        forward to tool-using agents."""

        from openjarvis.skills.manager import SkillManager
        from openjarvis.skills.overlay import SkillOverlay, write_overlay
        from openjarvis.skills.types import SkillManifest

        # Build an overlay so the manager picks up real few-shot examples
        overlay_dir = tmp_path / "overlays"
        write_overlay(
            SkillOverlay(
                skill_name="seeded-skill",
                optimizer="dspy",
                optimized_at="2026-04-08T00:00:00Z",
                trace_count=10,
                description="Optimized",
                few_shot=[{"input": "ping", "output": "pong"}],
            ),
            overlay_dir,
        )

        from openjarvis.core.events import EventBus

        mgr = SkillManager(bus=EventBus(), overlay_dir=overlay_dir)
        mgr._skills["seeded-skill"] = SkillManifest(
            name="seeded-skill",
            description="Original",
            markdown_content="Body",
        )
        mgr.discover()  # applies overlay

        # The captured examples should now contain our seeded one
        examples = mgr.get_few_shot_examples()
        assert len(examples) >= 1
        assert any("ping" in s and "pong" in s for s in examples)


class TestRunAgentForwardsExamples:
    def test_run_agent_passes_examples_to_tool_using_agent(self):
        """_run_agent injects system._skill_few_shot_examples into
        agent_kwargs when the agent class has accepts_tools=True."""
        from unittest.mock import patch

        from openjarvis.agents._stubs import AgentResult
        from openjarvis.system import JarvisSystem

        captured_kwargs: dict = {}

        class _CapturingAgent:
            accepts_tools = True

            def __init__(self, engine, model, **kwargs):
                captured_kwargs.update(kwargs)

            def run(self, query, context=None, **kw):
                return AgentResult(content="ok", turns=1)

        # Build a minimal JarvisSystem with the captured examples
        system = JarvisSystem.__new__(JarvisSystem)
        system.config = MagicMock()
        system.config.intelligence.temperature = 0.0
        system.config.intelligence.max_tokens = 100
        system.config.agent.max_turns = 5
        system.bus = MagicMock()
        system.engine = MagicMock()
        system.engine_key = "stub"
        system.model = "stub"
        system.tools = []
        system.tool_executor = None
        system.memory_backend = None
        system.channel_backend = None
        system.trace_store = None
        system.capability_policy = None
        system.session_store = None
        system._skill_few_shot_examples = ["### research-skill\nInput: q\nOutput: a"]
        system._mcp_clients = []

        with patch(
            "openjarvis.core.registry.AgentRegistry.get",
            return_value=_CapturingAgent,
        ):
            system._run_agent(
                query="test",
                messages=[],
                agent_name="capturing",
                tool_names=None,
                temperature=0.0,
                max_tokens=100,
            )

        assert "skill_few_shot_examples" in captured_kwargs
        assert captured_kwargs["skill_few_shot_examples"] == [
            "### research-skill\nInput: q\nOutput: a"
        ]
