"""Tests for OrchestratorAgent structured mode."""

from __future__ import annotations

import pytest

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, ToolSpec

# -- Mocks -------------------------------------------------------------------


class _MockEngine(InferenceEngine):
    """Engine that returns pre-scripted responses."""

    engine_id = "mock"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_idx = 0
        self.calls = []

    def generate(self, messages, **kwargs) -> dict:
        self.calls.append(list(messages))
        if self._call_idx < len(self._responses):
            content = self._responses[self._call_idx]
            self._call_idx += 1
        else:
            content = "FINAL_ANSWER: fallback"
        return {"content": content}

    def stream(self, messages, **kwargs):
        raise NotImplementedError

    def list_models(self):
        return []

    def health(self) -> bool:
        return True


class _MockTool(BaseTool):
    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description="A calculator",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                },
            },
        )

    def execute(self, **params) -> ToolResult:
        expr = params.get("expression", "")
        return ToolResult(tool_name="calculator", content=str(expr), success=True)


class _FileReadLikeTool(BaseTool):
    """Small test double with one required and one optional parameter."""

    tool_id = "file_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_read",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="file_read",
            content=params.get("path", ""),
            success=True,
        )


class _AmbiguousTool(BaseTool):
    """Test double whose bare input cannot map to one parameter safely."""

    tool_id = "copy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="copy",
            description="Copy a value",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source", "destination"],
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name="copy", content="copied", success=True)


class _CodeLikeTool(BaseTool):
    """Test double that explicitly accepts object-prefixed source text."""

    tool_id = "code"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="code",
            description="Execute source code",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
            metadata={"structured_allow_object_text": True},
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="code",
            content=params.get("code", ""),
            success=True,
        )


class _UnionStringTool(BaseTool):
    """Test double with a JSON Schema union that accepts strings."""

    tool_id = "union_file_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="union_file_read",
            description="Read a nullable path",
            parameters={
                "type": "object",
                "properties": {"path": {"type": ["string", "null"]}},
                "required": ["path"],
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="union_file_read",
            content=params.get("path", ""),
            success=True,
        )


# -- Tests -------------------------------------------------------------------


class TestStructuredMode:
    def test_thought_tool_input_then_final_answer(self):
        """Test full structured loop: TOOL call -> FINAL_ANSWER."""
        engine = _MockEngine(
            [
                "THOUGHT: I need to calculate\nTOOL: calculator\nINPUT: 2+2",
                "THOUGHT: Got result\nFINAL_ANSWER: 4",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
        )
        result = agent.run("What is 2+2?")
        assert result.content == "4"
        assert result.turns == 2
        assert len(result.tool_results) == 1
        assert result.tool_results[0].success is True
        assert result.tool_results[0].content == "2+2"

    @pytest.mark.parametrize(
        ("raw_input", "expected"),
        [
            ("notes/today.md", "notes/today.md"),
            ('"notes/today.md"', "notes/today.md"),
            ('{"path": "notes/today.md"}', "notes/today.md"),
            ("42", "42"),
            ("true", "true"),
            ("false", "false"),
            ("null", "null"),
            ("1e3", "1e3"),
            ('["notes/today.md"]', '["notes/today.md"]'),
            ('["notes/today.md",]', '["notes/today.md",]'),
            ("[draft] notes.md", "[draft] notes.md"),
            (
                "[x * 2 for x in range(3)]",
                "[x * 2 for x in range(3)]",
            ),
            ('"notes/today.md', '"notes/today.md'),
            ('""', ""),
            ('"{draft} notes.md"', "{draft} notes.md"),
            (r'"C:\\Users\\me\\notes.txt"', r"C:\Users\me\notes.txt"),
        ],
    )
    def test_single_string_parameter_accepts_text_input(self, raw_input, expected):
        """Structured text maps to the unambiguous string parameter."""
        engine = _MockEngine(
            [
                f"TOOL: file_read\nINPUT: {raw_input}",
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_FileReadLikeTool()],
            mode="structured",
        )

        result = agent.run("Read my notes")

        assert result.tool_results[0].success is True
        assert result.tool_results[0].content == expected

    @pytest.mark.parametrize(
        "raw_input",
        [
            '{"path": "notes/today.md",}',
            '{path: "notes/today.md"}',
            "{'path': 'notes/today.md'}",
            '{"unknown": 1, "path": "notes/today.md",}',
            r'{"pa\u0074h": "notes/today.md",}',
            '\ufeff{"path": "notes/today.md",}',
        ],
    )
    def test_malformed_json_like_input_remains_an_argument_error(self, raw_input):
        """Malformed JSON-looking text is not reclassified as a tool value."""
        engine = _MockEngine(
            [
                f"TOOL: file_read\nINPUT: {raw_input}",
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_FileReadLikeTool()],
            mode="structured",
        )

        result = agent.run("Read my notes")

        assert result.tool_results[0].success is False
        assert "Invalid arguments JSON" in result.tool_results[0].content
        assert "Tool 'file_read' failed: Invalid arguments JSON" in (
            engine.calls[1][-1].content
        )

    @pytest.mark.parametrize(
        "raw_input",
        [
            "{'code': value}",
            '{"code": object()}',
            "{'nested': {'value': 1}}",
        ],
    )
    def test_opted_in_tool_accepts_object_prefixed_text(self, raw_input):
        """Explicit raw-text metadata disambiguates dict-shaped source code."""
        engine = _MockEngine(
            [
                f"TOOL: code\nINPUT: {raw_input}",
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_CodeLikeTool()],
            mode="structured",
        )

        result = agent.run("Execute code")

        assert result.tool_results[0].success is True
        assert result.tool_results[0].content == raw_input

    def test_valid_object_remains_arguments_for_opted_in_tool(self):
        """Raw-text metadata does not override valid JSON argument objects."""
        engine = _MockEngine(
            [
                'TOOL: code\nINPUT: {"code": "print(1)"}',
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_CodeLikeTool()],
            mode="structured",
        )

        result = agent.run("Execute code")

        assert result.tool_results[0].success is True
        assert result.tool_results[0].content == "print(1)"

    def test_union_string_schema_accepts_json_scalar_text(self):
        """String unions normalize text that also parses as a JSON scalar."""
        engine = _MockEngine(
            [
                "TOOL: union_file_read\nINPUT: null",
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_UnionStringTool()],
            mode="structured",
        )

        result = agent.run("Read the path named null")

        assert result.tool_results[0].success is True
        assert result.tool_results[0].content == "null"

    def test_ambiguous_json_scalar_gets_stable_object_error(self):
        """Ambiguous valid JSON is rejected before tool dispatch."""
        engine = _MockEngine(
            [
                "TOOL: copy\nINPUT: 42",
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_AmbiguousTool()],
            mode="structured",
        )

        result = agent.run("Copy my notes")

        assert result.tool_results[0].success is False
        assert result.tool_results[0].content == (
            "Invalid arguments: expected a JSON object, got int."
        )
        assert "Tool 'copy' failed: Invalid arguments" in (engine.calls[1][-1].content)

    @pytest.mark.parametrize(
        "raw_input",
        [
            "notes/today.md",
            '{"source": "notes/today.md",}',
        ],
    )
    def test_multiple_required_parameters_do_not_guess_string_mapping(
        self,
        raw_input,
    ):
        """Ambiguous bare input remains invalid instead of choosing a field."""
        engine = _MockEngine(
            [
                f"TOOL: copy\nINPUT: {raw_input}",
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_AmbiguousTool()],
            mode="structured",
        )

        result = agent.run("Copy my notes")

        assert result.tool_results[0].success is False
        assert "Invalid arguments JSON" in result.tool_results[0].content

    def test_direct_final_answer(self):
        """Test that FINAL_ANSWER on first turn works."""
        engine = _MockEngine(
            [
                "THOUGHT: Easy\nFINAL_ANSWER: Paris",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
        )
        result = agent.run("Capital of France?")
        assert result.content == "Paris"
        assert result.turns == 1
        assert len(result.tool_results) == 0

    def test_no_tool_no_final_treats_as_answer(self):
        """If neither TOOL nor FINAL_ANSWER found, treat content as answer."""
        engine = _MockEngine(["Just a plain response with no format"])
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
        )
        result = agent.run("Hello")
        assert result.content == "Just a plain response with no format"
        assert result.turns == 1

    def test_max_turns(self):
        """Test that max_turns terminates the loop."""
        # Always returns a tool call, never a final answer
        responses = [
            "THOUGHT: calc\nTOOL: calculator\nINPUT: 1+1",
        ] * 5
        engine = _MockEngine(responses)
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
            max_turns=3,
        )
        result = agent.run("loop forever")
        assert result.turns == 3
        assert result.metadata.get("max_turns_exceeded") is True

    def test_custom_system_prompt(self):
        """Test that custom system_prompt is used."""
        engine = _MockEngine(["FINAL_ANSWER: ok"])
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
            system_prompt="Custom prompt here",
        )
        result = agent.run("test")
        assert result.content == "ok"


class TestFunctionCallingModeUnchanged:
    """Ensure function_calling mode still works as before."""

    def test_default_mode(self):
        engine = _MockEngine(["Hello back"])
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
        )
        # Default mode should be function_calling
        assert agent._mode == "function_calling"
        result = agent.run("Hello")
        assert result.content == "Hello back"


class TestParseStructuredResponse:
    def test_parse_thought_tool_input(self):
        parsed = OrchestratorAgent._parse_structured_response(
            "THOUGHT: reasoning\nTOOL: calculator\nINPUT: 2+2"
        )
        assert parsed["thought"] == "reasoning"
        assert parsed["tool"] == "calculator"
        assert parsed["input"] == "2+2"
        assert parsed["final_answer"] == ""

    def test_parse_final_answer(self):
        parsed = OrchestratorAgent._parse_structured_response(
            "THOUGHT: done\nFINAL_ANSWER: 42"
        )
        assert parsed["final_answer"] == "42"
        assert parsed["thought"] == "done"

    def test_parse_empty(self):
        parsed = OrchestratorAgent._parse_structured_response("")
        assert parsed["thought"] == ""
        assert parsed["tool"] == ""
        assert parsed["final_answer"] == ""
