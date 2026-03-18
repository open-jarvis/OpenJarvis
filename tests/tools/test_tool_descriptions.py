"""Tests for the shared build_tool_descriptions() builder."""

from __future__ import annotations

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import (
    BaseTool,
    ToolSpec,
    build_tool_descriptions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CalcTool(BaseTool):
    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description="Evaluate a mathematical expression safely.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "Math expression to evaluate (e.g. '2+3*4', 'sqrt(16)')"
                        ),
                    },
                },
                "required": ["expression"],
            },
            category="math",
            cost_estimate=0.0,
            latency_estimate=0.0,
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name="calculator", content="0", success=True)


class _WebSearchTool(BaseTool):
    tool_id = "web_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description="Search the web for real-time information.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return",
                    },
                },
                "required": ["query"],
            },
            category="utility",
            cost_estimate=0.001,
            latency_estimate=2.0,
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name="web_search", content="", success=True)


class _NoCategoryTool(BaseTool):
    tool_id = "think"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="think",
            description="Internal reasoning scratchpad.",
            parameters={
                "type": "object",
                "properties": {
                    "thought": {"type": "string"},
                },
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name="think", content="", success=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildToolDescriptions:
    def test_empty_list_returns_no_tools(self):
        assert build_tool_descriptions([]) == "No tools available."

    def test_single_tool_name_present(self):
        result = build_tool_descriptions([_CalcTool()])
        assert "### calculator" in result

    def test_description_present(self):
        result = build_tool_descriptions([_CalcTool()])
        assert "Evaluate a mathematical expression safely." in result

    def test_parameter_type_and_required(self):
        result = build_tool_descriptions([_CalcTool()])
        assert "expression" in result
        assert "string" in result
        assert "required" in result

    def test_parameter_description(self):
        result = build_tool_descriptions([_CalcTool()])
        assert "Math expression to evaluate" in result

    def test_optional_parameter_no_required_marker(self):
        result = build_tool_descriptions([_WebSearchTool()])
        # max_results is optional
        assert "max_results" in result
        # The line for max_results should not say "required"
        for line in result.splitlines():
            if "max_results" in line:
                assert "required" not in line

    def test_category_shown_by_default(self):
        result = build_tool_descriptions([_CalcTool()])
        assert "Category: math" in result

    def test_category_hidden_when_disabled(self):
        result = build_tool_descriptions([_CalcTool()], include_category=False)
        assert "Category:" not in result

    def test_empty_category_not_shown(self):
        result = build_tool_descriptions([_NoCategoryTool()])
        assert "Category:" not in result

    def test_cost_hidden_by_default(self):
        result = build_tool_descriptions([_WebSearchTool()])
        assert "Cost estimate:" not in result

    def test_cost_shown_when_enabled(self):
        result = build_tool_descriptions([_WebSearchTool()], include_cost=True)
        assert "Cost estimate:" in result
        assert "Latency estimate:" in result

    def test_zero_cost_not_shown(self):
        result = build_tool_descriptions([_CalcTool()], include_cost=True)
        # cost_estimate is 0.0, so should not show
        assert "Cost estimate:" not in result

    def test_multiple_tools(self):
        result = build_tool_descriptions([_CalcTool(), _WebSearchTool()])
        assert "### calculator" in result
        assert "### web_search" in result

    def test_tool_without_parameters(self):
        """Tool with empty parameters dict."""

        class _EmptyParamTool(BaseTool):
            tool_id = "noop"

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(name="noop", description="Does nothing.")

            def execute(self, **params) -> ToolResult:
                return ToolResult(tool_name="noop", content="", success=True)

        result = build_tool_descriptions([_EmptyParamTool()])
        assert "### noop" in result
        assert "Does nothing." in result
        # No Parameters section since no properties
        assert "Parameters:" not in result
