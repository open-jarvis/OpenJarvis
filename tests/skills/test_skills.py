"""Tests for skill system (Phase 15.2)."""

from __future__ import annotations

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.types import SkillManifest, SkillStep
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class EchoTool(BaseTool):
    """Simple tool that echoes input."""

    tool_id = "echo"

    @property
    def spec(self):
        return ToolSpec(name="echo", description="Echo input")

    def execute(self, **params):
        return ToolResult(
            tool_name="echo",
            content=params.get("text", ""),
            success=True,
        )


class UpperTool(BaseTool):
    """Simple tool that uppercases input."""

    tool_id = "upper"

    @property
    def spec(self):
        return ToolSpec(name="upper", description="Uppercase input")

    def execute(self, **params):
        return ToolResult(
            tool_name="upper",
            content=params.get("text", "").upper(),
            success=True,
        )


class TestSkillManifest:
    def test_create_manifest(self):
        manifest = SkillManifest(
            name="test_skill",
            version="0.1.0",
            steps=[SkillStep(tool_name="echo", output_key="result")],
        )
        assert manifest.name == "test_skill"
        assert len(manifest.steps) == 1

    def test_manifest_bytes(self):
        manifest = SkillManifest(name="test", steps=[])
        data = manifest.manifest_bytes()
        assert isinstance(data, bytes)
        assert b"test" in data


class TestSkillExecutor:
    def _make_executor(self):
        tools = [EchoTool(), UpperTool()]
        tool_executor = ToolExecutor(tools)
        return SkillExecutor(tool_executor)

    def test_single_step(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="single",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "hello"}',
                    output_key="result",
                )
            ],
        )
        result = executor.run(manifest)
        assert result.success
        assert result.context.get("result") == "hello"

    def test_multi_step_pipeline(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="pipeline",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "hello world"}',
                    output_key="echoed",
                ),
                SkillStep(
                    tool_name="upper",
                    arguments_template='{"text": "{echoed}"}',
                    output_key="uppered",
                ),
            ],
        )
        result = executor.run(manifest)
        assert result.success
        assert result.context.get("uppered") == "HELLO WORLD"

    def test_step_failure_stops_pipeline(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="failing",
            steps=[
                SkillStep(tool_name="nonexistent", output_key="x"),
                SkillStep(tool_name="echo", output_key="y"),
            ],
        )
        result = executor.run(manifest)
        assert not result.success
        assert len(result.step_results) == 1

    def test_initial_context(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="with_ctx",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{greeting}"}',
                    output_key="result",
                )
            ],
        )
        result = executor.run(manifest, initial_context={"greeting": "hi"})
        assert result.success
        assert result.context.get("result") == "hi"

    def test_events_emitted(self):
        bus = EventBus(record_history=True)
        tools = [EchoTool()]
        tool_executor = ToolExecutor(tools)
        executor = SkillExecutor(tool_executor, bus=bus)

        manifest = SkillManifest(
            name="evented",
            steps=[SkillStep(tool_name="echo", arguments_template='{"text": "x"}')],
        )
        executor.run(manifest)
        event_types = {e.event_type for e in bus.history}
        assert EventType.SKILL_EXECUTE_START in event_types
        assert EventType.SKILL_EXECUTE_END in event_types


class TestSkillStepExtended:
    def test_step_with_skill_name(self):
        step = SkillStep(skill_name="summarize", output_key="result")
        assert step.skill_name == "summarize"
        assert step.tool_name == ""

    def test_step_either_tool_or_skill(self):
        step_tool = SkillStep(tool_name="web_search")
        step_skill = SkillStep(skill_name="summarize")
        assert step_tool.tool_name == "web_search"
        assert step_tool.skill_name == ""
        assert step_skill.skill_name == "summarize"
        assert step_skill.tool_name == ""


class TestSkillManifestExtended:
    def test_manifest_with_tags_and_depends(self):
        manifest = SkillManifest(
            name="test",
            tags=["research"],
            depends=["summarize"],
        )
        assert manifest.tags == ["research"]
        assert manifest.depends == ["summarize"]

    def test_manifest_with_invocation_flags(self):
        manifest = SkillManifest(
            name="test",
            user_invocable=False,
            disable_model_invocation=True,
        )
        assert not manifest.user_invocable
        assert manifest.disable_model_invocation

    def test_manifest_with_markdown_content(self):
        manifest = SkillManifest(
            name="test",
            markdown_content="When asked to research...",
        )
        assert manifest.markdown_content == "When asked to research..."

    def test_manifest_bytes_includes_new_fields(self):
        manifest = SkillManifest(
            name="test",
            tags=["a"],
            depends=["b"],
            steps=[],
        )
        data = manifest.manifest_bytes()
        assert b"tags" in data
        assert b"depends" in data


class TestSkillExecutorSubSkills:
    def test_sub_skill_delegation(self):
        """Executor delegates skill_name steps to a skill resolver."""
        tools = [EchoTool(), UpperTool()]
        tool_executor = ToolExecutor(tools)
        executor = SkillExecutor(tool_executor)

        child_manifest = SkillManifest(
            name="upper_skill",
            steps=[
                SkillStep(
                    tool_name="upper",
                    arguments_template='{"text": "{text}"}',
                    output_key="uppered",
                ),
            ],
        )

        def resolve_skill(name, context):
            from openjarvis.skills.executor import SkillResult

            if name == "upper_skill":
                return executor.run(child_manifest, initial_context=context)
            return SkillResult(skill_name=name, success=False)

        executor.set_skill_resolver(resolve_skill)

        parent_manifest = SkillManifest(
            name="parent",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "hello"}',
                    output_key="echoed",
                ),
                SkillStep(
                    skill_name="upper_skill",
                    arguments_template='{"text": "{echoed}"}',
                    output_key="result",
                ),
            ],
        )
        result = executor.run(parent_manifest)
        assert result.success
        assert result.context.get("result") == "HELLO"

    def test_sub_skill_failure_stops_pipeline(self):
        tools = [EchoTool()]
        tool_executor = ToolExecutor(tools)
        executor = SkillExecutor(tool_executor)

        def resolve_skill(name, context):
            from openjarvis.skills.executor import SkillResult

            return SkillResult(skill_name=name, success=False)

        executor.set_skill_resolver(resolve_skill)

        manifest = SkillManifest(
            name="parent",
            steps=[
                SkillStep(skill_name="nonexistent", output_key="x"),
                SkillStep(tool_name="echo", output_key="y"),
            ],
        )
        result = executor.run(manifest)
        assert not result.success
        assert len(result.step_results) == 1


class TestSkillTool:
    def test_skill_as_tool(self):
        from openjarvis.skills.tool_adapter import SkillTool

        tools = [EchoTool()]
        tool_executor = ToolExecutor(tools)
        executor = SkillExecutor(tool_executor)
        manifest = SkillManifest(
            name="tool_skill",
            description="A skill exposed as a tool",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{input}"}',
                    output_key="result",
                )
            ],
        )
        skill_tool = SkillTool(manifest, executor)
        assert skill_tool.spec.name == "skill_tool_skill"
        result = skill_tool.execute(input="hello")
        assert result.success
