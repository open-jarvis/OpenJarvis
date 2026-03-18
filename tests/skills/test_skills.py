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
