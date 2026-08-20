"""Tests for SkillTool metadata tagging (Plan 2A trace tagging)."""

from __future__ import annotations

from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.tool_adapter import SkillTool
from openjarvis.skills.types import SkillManifest, SkillStep
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class _EchoTool(BaseTool):
    tool_id = "echo"

    @property
    def spec(self):
        return ToolSpec(name="echo", description="echo")

    def execute(self, **params):
        return ToolResult(
            tool_name="echo",
            content=params.get("text", ""),
            success=True,
        )


class TestSkillToolMetadataTagging:
    def _make_tool(self, manifest: SkillManifest) -> SkillTool:
        executor = SkillExecutor(ToolExecutor([_EchoTool()]))
        return SkillTool(manifest, executor)

    def test_metadata_includes_skill_name(self):
        manifest = SkillManifest(
            name="my-skill",
            description="A test skill",
            markdown_content="Just instructions",
        )
        tool = self._make_tool(manifest)
        result = tool.execute(task="hello")
        assert result.metadata["skill"] == "my-skill"

    def test_skill_source_defaults_to_user(self):
        manifest = SkillManifest(
            name="my-skill",
            description="A test skill",
            markdown_content="Just instructions",
        )
        tool = self._make_tool(manifest)
        result = tool.execute(task="hello")
        assert result.metadata["skill_source"] == "user"

    def test_skill_source_propagates_from_manifest(self):
        manifest = SkillManifest(
            name="apple-notes",
            description="Apple Notes",
            markdown_content="Use memo",
            metadata={"openjarvis": {"source": "hermes"}},
        )
        tool = self._make_tool(manifest)
        result = tool.execute(task="create a note")
        assert result.metadata["skill_source"] == "hermes"

    def test_skill_kind_instructional_when_no_steps(self):
        manifest = SkillManifest(
            name="explainer",
            description="Explains things",
            markdown_content="Explain step by step",
        )
        tool = self._make_tool(manifest)
        result = tool.execute(task="explain a loop")
        assert result.metadata["skill_kind"] == "instructional"

    def test_skill_kind_executable_when_steps_present(self):
        manifest = SkillManifest(
            name="echo-skill",
            description="Echoes input",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{input}"}',
                    output_key="result",
                ),
            ],
        )
        tool = self._make_tool(manifest)
        result = tool.execute(input="hello")
        assert result.metadata["skill_kind"] == "executable"

    def test_failed_pipeline_still_tags_metadata(self):
        manifest = SkillManifest(
            name="broken",
            description="Calls nonexistent tool",
            steps=[
                SkillStep(
                    tool_name="nonexistent_tool",
                    arguments_template="{}",
                    output_key="x",
                ),
            ],
        )
        tool = self._make_tool(manifest)
        result = tool.execute()
        assert result.success is False
        assert result.metadata["skill"] == "broken"
        assert result.metadata["skill_kind"] == "executable"
