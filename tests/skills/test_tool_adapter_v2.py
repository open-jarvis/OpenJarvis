"""Tests for SkillTool v2 — parameter extraction and markdown support."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.tool_adapter import SkillTool
from openjarvis.skills.types import SkillManifest, SkillStep
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class EchoTool(BaseTool):
    tool_id = "echo"

    @property
    def spec(self):
        return ToolSpec(name="echo", description="Echo input")

    def execute(self, **params):
        return ToolResult(
            tool_name="echo", content=params.get("text", ""), success=True
        )


def _make_executor(*extra_tools):
    tools = [EchoTool(), *extra_tools]
    tool_executor = ToolExecutor(tools)
    return SkillExecutor(tool_executor)


class _RememberingMenu(BaseTool):
    tool_id = "display_menu"

    @property
    def spec(self):
        return ToolSpec(name="display_menu", description="Show a menu")

    def execute(self, **params):
        return ToolResult(tool_name="display_menu", content="shown")

    def agent_context(self):
        return {"displayed_menu": [{"id": "v-1", "name": "Taco gà", "price": 86000}]}


def test_menu_skill_forwards_the_displayed_menu_to_the_agent():
    manifest = SkillManifest(
        name="site-menu",
        steps=[SkillStep(tool_name="display_menu", arguments_template="{}")],
    )

    tool = SkillTool(manifest, _make_executor(_RememberingMenu()))

    assert tool.agent_context() == {
        "displayed_menu": [{"id": "v-1", "name": "Taco gà", "price": 86000}]
    }


def test_skill_without_a_menu_step_adds_no_agent_context():
    manifest = SkillManifest(
        name="echo-skill",
        steps=[SkillStep(tool_name="echo", arguments_template='{"text":"x"}')],
    )

    tool = SkillTool(manifest, _make_executor(_RememberingMenu()))

    assert tool.agent_context() == {}


class TestParameterExtraction:
    @pytest.mark.parametrize(
        "schema, expected",
        [
            (
                {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
                {"q"},
            ),
            (
                {
                    "type": "object",
                    "properties": {
                        "department_code": {"type": "string"},
                        "day": {"type": "integer"},
                    },
                    "required": ["department_code", "day"],
                    "additionalProperties": False,
                },
                {"department_code", "day"},
            ),
        ],
    )
    def test_explicit_schema_exposes_exact_declared_names(self, schema, expected):
        manifest = SkillManifest(
            name="native-search",
            input_schema=schema,
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text":"{q|urlencode}"}',
                )
            ],
        )

        parameters = SkillTool(manifest, _make_executor()).spec.parameters

        assert set(parameters["properties"]) == expected
        assert parameters == schema
        assert parameters is not schema

    def test_filtered_placeholder_does_not_invent_filter_parameter(self):
        manifest = SkillManifest(
            name="filtered",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text":"{q|urlencode}"}',
                )
            ],
        )

        props = SkillTool(manifest, _make_executor()).spec.parameters["properties"]

        assert set(props) == {"q"}

    def test_pipeline_params_extracted(self):
        """Placeholders in arguments_template become input params."""
        manifest = SkillManifest(
            name="pipe_skill",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{query}"}',
                    output_key="echoed",
                )
            ],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        props = skill_tool.spec.parameters.get("properties", {})
        assert "query" in props

    def test_output_keys_not_exposed_as_params(self):
        """output_key values from prior steps are not exposed as input params."""
        manifest = SkillManifest(
            name="chain_skill",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "hello"}',
                    output_key="echoed",
                ),
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{echoed}"}',
                    output_key="result",
                ),
            ],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        props = skill_tool.spec.parameters.get("properties", {})
        # "echoed" is produced by step 1, so it should NOT be an input param
        assert "echoed" not in props

    def test_dotted_produced_output_root_is_not_exposed_as_param(self):
        """A dotted reference to a prior result is internal pipeline context."""
        manifest = SkillManifest(
            name="order_chain",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template=(
                        '{"text": "{\\"order\\": {\\"id\\": \\"ord-123\\"}}"}'
                    ),
                    output_key="step_0",
                ),
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{step_0.order.id}"}',
                    output_key="step_1",
                ),
            ],
        )

        props = SkillTool(manifest, _make_executor()).spec.parameters["properties"]

        assert "step_0" not in props
        assert "step_0.order.id" not in props

    def test_instruction_only_skill_gets_task_param(self):
        """Skills with no steps (markdown-only) expose an optional 'task' param."""
        manifest = SkillManifest(
            name="md_only",
            markdown_content="When asked to research, follow these steps...",
            steps=[],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        props = skill_tool.spec.parameters.get("properties", {})
        assert "task" in props

    def test_no_extra_params_for_pipeline_skill(self):
        """Pipeline skills don't get a spurious 'task' param."""
        manifest = SkillManifest(
            name="echo_skill",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{msg}"}',
                    output_key="out",
                )
            ],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        props = skill_tool.spec.parameters.get("properties", {})
        assert "msg" in props
        assert "task" not in props

    def test_multiple_placeholders_across_steps(self):
        """Multiple distinct placeholders across steps are all exposed."""
        manifest = SkillManifest(
            name="multi_param",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{first}"}',
                    output_key="out1",
                ),
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{second}"}',
                    output_key="out2",
                ),
            ],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        props = skill_tool.spec.parameters.get("properties", {})
        assert "first" in props
        assert "second" in props


class TestExplicitParameterValidation:
    @pytest.mark.parametrize(
        "params, field",
        [
            ({"count": 1, "mode": "brief"}, "q"),
            ({"q": "ok", "count": 1, "mode": "brief", "extra": "x"}, "extra"),
            ({"q": 123, "count": 1, "mode": "brief"}, "q"),
            ({"q": "", "count": 1, "mode": "brief"}, "q"),
            ({"q": "ok", "count": 0, "mode": "brief"}, "count"),
            ({"q": "ok", "count": 4, "mode": "brief"}, "count"),
            ({"q": "ok", "count": 1, "mode": "secret-mode"}, "mode"),
        ],
    )
    def test_invalid_arguments_never_call_executor(self, params, field):
        schema = {
            "type": "object",
            "properties": {
                "q": {"type": "string", "minLength": 1},
                "count": {"type": "integer", "minimum": 1, "maximum": 3},
                "mode": {"type": "string", "enum": ["brief", "full"]},
            },
            "required": ["q", "count", "mode"],
            "additionalProperties": False,
        }
        executor = _make_executor()
        executor.run = Mock()
        tool = SkillTool(
            SkillManifest(
                name="validated",
                input_schema=schema,
                steps=[
                    SkillStep(tool_name="echo", arguments_template='{"text":"{q}"}')
                ],
            ),
            executor,
        )

        result = tool.execute(**params)

        assert not result.success
        assert result.content.startswith("invalid_skill_arguments:")
        assert field in result.content
        assert "secret-mode" not in result.content
        executor.run.assert_not_called()

    def test_valid_arguments_reach_executor_without_coercion(self):
        schema = {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"active": {"type": "boolean"}},
                        "required": ["active"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["q", "filters"],
            "additionalProperties": False,
        }
        tool = SkillTool(
            SkillManifest(
                name="validated",
                input_schema=schema,
                steps=[
                    SkillStep(tool_name="echo", arguments_template='{"text":"{q}"}')
                ],
            ),
            _make_executor(),
        )

        result = tool.execute(q="coffee", filters=[{"active": True}])

        assert result.success
        assert result.content == "coffee"


class TestMarkdownReturn:
    def test_instruction_only_returns_markdown(self):
        """Instruction-only skill (no steps) returns markdown_content as result."""
        manifest = SkillManifest(
            name="md_skill",
            markdown_content="## Instructions\nDo the thing.",
            steps=[],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        result = skill_tool.execute(task="some task")
        assert result.success
        assert "## Instructions" in result.content

    def test_instruction_only_no_task_param_still_works(self):
        """Instruction-only skill works even without task param."""
        manifest = SkillManifest(
            name="md_skill2",
            markdown_content="Follow these instructions.",
            steps=[],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        result = skill_tool.execute()
        assert result.success
        assert "Follow these instructions." in result.content

    def test_hybrid_returns_pipeline_result_and_markdown(self):
        """Hybrid skill (steps + markdown) returns both pipeline output and markdown."""
        manifest = SkillManifest(
            name="hybrid_skill",
            markdown_content="## Guidance\nExtra context.",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{input}"}',
                    output_key="result",
                )
            ],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        result = skill_tool.execute(input="hello world")
        assert result.success
        # Pipeline output is present
        assert "hello world" in result.content
        # Markdown is appended
        assert "## Guidance" in result.content

    def test_pipeline_failure_is_propagated(self):
        """If the pipeline fails, the ToolResult is not successful."""
        manifest = SkillManifest(
            name="broken_skill",
            steps=[
                SkillStep(tool_name="nonexistent_tool", output_key="x"),
            ],
        )
        skill_tool = SkillTool(manifest, _make_executor())
        result = skill_tool.execute()
        assert not result.success

    def test_tool_id_uses_skill_prefix(self):
        """tool_id is prefixed with 'skill_'."""
        manifest = SkillManifest(name="my_skill", steps=[])
        skill_tool = SkillTool(manifest, _make_executor())
        assert skill_tool.tool_id == "skill_my_skill"

    def test_spec_name_uses_skill_prefix(self):
        """spec.name is prefixed with 'skill_'."""
        manifest = SkillManifest(name="another_skill", steps=[])
        skill_tool = SkillTool(manifest, _make_executor())
        assert skill_tool.spec.name == "skill_another_skill"

    def test_spec_category_is_skill(self):
        """spec.category is always 'skill'."""
        manifest = SkillManifest(name="cat_skill", steps=[])
        skill_tool = SkillTool(manifest, _make_executor())
        assert skill_tool.spec.category == "skill"

    def test_skill_manager_kwarg_accepted(self):
        """Constructor accepts optional skill_manager keyword argument."""
        manifest = SkillManifest(name="mgr_skill", steps=[])
        # Should not raise
        skill_tool = SkillTool(manifest, _make_executor(), skill_manager=None)
        assert skill_tool.tool_id == "skill_mgr_skill"
