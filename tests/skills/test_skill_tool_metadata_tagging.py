"""Tests for SkillTool metadata tagging (Plan 2A trace tagging)."""

from __future__ import annotations

from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.tool_adapter import SkillTool
from openjarvis.skills.types import SkillManifest, SkillStep
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec
from openjarvis.tools.display import DisplayCartTool


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
    def test_direct_checkout_exposes_replacement_lines_on_an_empty_cart(self):
        cart = DisplayCartTool()
        manifest = SkillManifest(
            name="checkout",
            checkout=True,
            accepts_cart_lines=True,
            steps=[SkillStep(tool_name="echo")],
        )
        tool = SkillTool(manifest, SkillExecutor(ToolExecutor([cart, _EchoTool()])))

        assert tool.agent_context() == {"draft_cart": None}
        assert tool.spec.parameters["properties"]["cart_lines"]["type"] == "array"
        assert tool.spec.parameters["oneOf"] == [
            {"required": ["cart_revision"]},
            {"required": ["cart_lines"]},
        ]

    def test_final_display_message_and_completion_survive_skill_wrapper(self):
        class Display(_EchoTool):
            def execute(self, **params):
                return ToolResult(
                    tool_name="display_payment_qr",
                    content="shown",
                    success=True,
                    metadata={
                        "customer_message": "Scan to pay",
                        "completed_display": True,
                        "result_complete": True,
                        "projected_count": 12,
                        "published_count": 12,
                    },
                )

        manifest = SkillManifest(name="checkout", steps=[SkillStep(tool_name="echo")])
        tool = SkillTool(manifest, SkillExecutor(ToolExecutor([Display()])))
        result = tool.execute()
        assert result.metadata["completed_display"] is True
        assert result.metadata["customer_message"] == "Scan to pay"
        assert result.metadata["result_complete"] is True
        assert result.metadata["projected_count"] == 12
        assert result.metadata["published_count"] == 12
        assert result.metadata["skill"] == "checkout"

    def test_completed_menu_does_not_fallback_to_model_supplied_message(self):
        class Display(_EchoTool):
            def execute(self, **params):
                return ToolResult(
                    tool_name="display_menu",
                    content="shown",
                    success=True,
                    metadata={"completed_display": True},
                )

        manifest = SkillManifest(
            name="menu",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"customer_message":"{customer_message}"}',
                )
            ],
        )
        tool = SkillTool(manifest, SkillExecutor(ToolExecutor([Display()])))

        result = tool.execute(customer_message="untrusted narration")

        assert result.metadata["completed_display"] is True
        assert "customer_message" not in result.metadata

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
