"""Tests for openjarvis.learning.spec_search.diagnose.teacher_agent module.

All tests use a mocked CloudEngine — no live API calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from openjarvis.learning.spec_search.diagnose.types import DiagnosticTool


def _make_tool(
    name: str = "test_tool", return_value: str = "tool result"
) -> DiagnosticTool:
    """Create a minimal diagnostic tool for testing."""
    return DiagnosticTool(
        name=name,
        description=f"A test tool named {name}",
        parameters={"type": "object", "properties": {"arg": {"type": "string"}}},
        fn=lambda **kwargs: return_value,
    )


def _make_engine_response(
    content: str = "",
    tool_calls: list | None = None,
    cost_usd: float = 0.01,
) -> dict:
    """Create a mock engine.generate() response."""
    resp = {
        "content": content,
        "finish_reason": "stop" if not tool_calls else "tool_calls",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        "cost_usd": cost_usd,
    }
    if tool_calls:
        resp["tool_calls"] = tool_calls
    return resp


class TestTeacherAgentNoTools:
    """Teacher responds without using any tools."""

    def test_returns_content_from_single_turn(self) -> None:
        from openjarvis.learning.spec_search.diagnose.teacher_agent import (
            TeacherAgent,
        )

        engine = MagicMock()
        engine.generate.return_value = _make_engine_response(
            content="## Diagnosis\nThe student struggles with math routing."
        )

        agent = TeacherAgent(
            engine=engine,
            model="claude-opus-4-6",
            tools=[],
            max_turns=5,
            max_cost_usd=5.0,
        )
        result = agent.run("Analyze student failures.")

        assert "math routing" in result.content
        assert result.turns == 1
        assert result.total_cost_usd > 0

    def test_tracks_cost(self) -> None:
        from openjarvis.learning.spec_search.diagnose.teacher_agent import (
            TeacherAgent,
        )

        engine = MagicMock()
        engine.generate.return_value = _make_engine_response(
            content="Done", cost_usd=0.05
        )

        agent = TeacherAgent(
            engine=engine,
            model="claude-opus-4-6",
            tools=[],
            max_turns=5,
            max_cost_usd=5.0,
        )
        result = agent.run("Analyze.")
        assert result.total_cost_usd == 0.05


class TestTeacherAgentWithTools:
    """Teacher uses tools in a multi-turn loop."""

    def test_executes_tool_call_and_continues(self) -> None:
        from openjarvis.learning.spec_search.diagnose.teacher_agent import (
            TeacherAgent,
        )

        engine = MagicMock()
        # Turn 1: teacher calls a tool
        tool_call_response = _make_engine_response(
            content="Let me look at the traces.",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "test_tool",
                    "arguments": json.dumps({"arg": "value"}),
                }
            ],
        )
        # Turn 2: teacher produces final answer
        final_response = _make_engine_response(
            content="## Diagnosis\nBased on the traces, I found...",
        )
        engine.generate.side_effect = [tool_call_response, final_response]

        tool = _make_tool("test_tool", return_value="trace data here")
        agent = TeacherAgent(
            engine=engine,
            model="claude-opus-4-6",
            tools=[tool],
            max_turns=5,
            max_cost_usd=5.0,
        )
        result = agent.run("Diagnose failures.")

        assert result.turns == 2
        assert "Based on the traces" in result.content
        assert len(result.tool_call_records) == 1
        assert result.tool_call_records[0].tool == "test_tool"

    def test_stops_at_max_turns(self) -> None:
        from openjarvis.learning.spec_search.diagnose.teacher_agent import (
            TeacherAgent,
        )

        engine = MagicMock()
        # Every turn calls a tool — should stop after max_turns
        engine.generate.return_value = _make_engine_response(
            content="",
            tool_calls=[
                {
                    "id": "call_loop",
                    "name": "test_tool",
                    "arguments": "{}",
                }
            ],
        )

        tool = _make_tool("test_tool")
        agent = TeacherAgent(
            engine=engine,
            model="claude-opus-4-6",
            tools=[tool],
            max_turns=3,
            max_cost_usd=5.0,
        )
        result = agent.run("Diagnose.")

        assert result.turns == 3

    def test_stops_at_max_cost(self) -> None:
        from openjarvis.learning.spec_search.diagnose.teacher_agent import (
            TeacherAgent,
        )

        engine = MagicMock()
        # Each call costs 2.0 — should stop after exceeding max_cost
        engine.generate.return_value = _make_engine_response(
            content="",
            tool_calls=[
                {
                    "id": "call_cost",
                    "name": "test_tool",
                    "arguments": "{}",
                }
            ],
            cost_usd=2.0,
        )

        tool = _make_tool("test_tool")
        agent = TeacherAgent(
            engine=engine,
            model="claude-opus-4-6",
            tools=[tool],
            max_turns=100,
            max_cost_usd=3.0,
        )
        result = agent.run("Diagnose.")

        assert result.total_cost_usd >= 2.0
        # Should have stopped before exhausting all 100 turns
        assert result.turns < 100

    def test_multiple_tool_calls_in_one_turn(self) -> None:
        from openjarvis.learning.spec_search.diagnose.teacher_agent import (
            TeacherAgent,
        )

        engine = MagicMock()
        # Turn 1: two tool calls
        multi_call = _make_engine_response(
            content="Checking multiple things.",
            tool_calls=[
                {"id": "call_a", "name": "tool_a", "arguments": "{}"},
                {"id": "call_b", "name": "tool_b", "arguments": "{}"},
            ],
        )
        final = _make_engine_response(content="All done.")
        engine.generate.side_effect = [multi_call, final]

        tool_a = _make_tool("tool_a", "result_a")
        tool_b = _make_tool("tool_b", "result_b")
        agent = TeacherAgent(
            engine=engine,
            model="claude-opus-4-6",
            tools=[tool_a, tool_b],
            max_turns=5,
            max_cost_usd=5.0,
        )
        result = agent.run("Diagnose.")

        assert result.turns == 2
        assert len(result.tool_call_records) == 2


class TestTeacherAgentResult:
    """Tests for TeacherAgentResult structure."""

    def test_result_has_all_fields(self) -> None:
        from openjarvis.learning.spec_search.diagnose.teacher_agent import (
            TeacherAgent,
        )

        engine = MagicMock()
        engine.generate.return_value = _make_engine_response(
            content="Diagnosis here.", cost_usd=0.1
        )

        agent = TeacherAgent(
            engine=engine,
            model="claude-opus-4-6",
            tools=[],
            max_turns=5,
            max_cost_usd=5.0,
        )
        result = agent.run("Go.", system_prompt="You are a meta-engineer.")

        assert hasattr(result, "content")
        assert hasattr(result, "turns")
        assert hasattr(result, "total_cost_usd")
        assert hasattr(result, "tool_call_records")
        assert hasattr(result, "total_tokens")
