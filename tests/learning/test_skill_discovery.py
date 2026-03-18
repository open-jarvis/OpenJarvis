"""Tests for SkillDiscovery — mining recurring tool sequences from traces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from openjarvis.learning.agents.skill_discovery import SkillDiscovery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _Step:
    step_type: str = "tool_call"
    tool_name: str = ""
    name: str = ""  # fallback


@dataclass
class _StepEnum:
    """Step with an enum-like step_type that has a .value attribute."""

    class _StepType:
        def __init__(self, val: str) -> None:
            self.value = val

        def __str__(self) -> str:
            return self.value

    step_type: object = None
    tool_name: str = ""

    def __post_init__(self) -> None:
        if self.step_type is None:
            self.step_type = self._StepType("tool_call")


@dataclass
class _Trace:
    query: str = ""
    outcome: float = 1.0
    steps: list = field(default_factory=list)


def _make_trace(tools: List[str], outcome: float = 1.0, query: str = "") -> _Trace:
    steps = [_Step(step_type="tool_call", tool_name=t) for t in tools]
    return _Trace(query=query, outcome=outcome, steps=steps)


def _make_dict_trace(tools: List[str], outcome: float = 1.0, query: str = "") -> dict:
    steps = [{"step_type": "tool_call", "tool_name": t} for t in tools]
    return {"query": query, "outcome": outcome, "steps": steps}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    def test_empty_traces(self):
        sd = SkillDiscovery()
        result = sd.analyze_traces([])
        assert result == []
        assert sd.discovered_skills == []

    def test_single_trace_below_threshold(self):
        """One trace cannot meet min_frequency=3."""
        sd = SkillDiscovery(min_frequency=3)
        traces = [_make_trace(["web_search", "file_write"], outcome=1.0)]
        result = sd.analyze_traces(traces)
        assert result == []

    def test_recurring_sequence(self):
        """3+ traces with same 2-tool sequence should be discovered."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.5)
        traces = [
            _make_trace(["web_search", "file_write"], outcome=0.9, query=f"q{i}")
            for i in range(5)
        ]
        result = sd.analyze_traces(traces)
        assert len(result) >= 1
        # The web_search_file_write sequence should appear
        names = [s.name for s in result]
        assert "web_search_file_write" in names
        skill = [s for s in result if s.name == "web_search_file_write"][0]
        assert skill.frequency == 5
        assert skill.tool_sequence == ["web_search", "file_write"]
        assert skill.avg_outcome >= 0.5

    def test_outcome_threshold(self):
        """Low-outcome sequences should be filtered out."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.8)
        traces = [_make_trace(["a", "b"], outcome=0.3) for _ in range(5)]
        result = sd.analyze_traces(traces)
        assert result == []

    def test_sequence_length_limits(self):
        """Sequences shorter than min or longer than max should be excluded."""
        # Only length-1 tools (below min_sequence_length=2)
        sd = SkillDiscovery(
            min_frequency=2,
            min_sequence_length=2,
            max_sequence_length=3,
        )
        short_traces = [_make_trace(["a"], outcome=1.0) for _ in range(5)]
        result = sd.analyze_traces(short_traces)
        assert result == []

        # Long sequence: with max_sequence_length=2, a 4-tool sequence
        # should only produce subsequences of length 2
        sd2 = SkillDiscovery(
            min_frequency=3,
            min_sequence_length=2,
            max_sequence_length=2,
        )
        long_traces = [_make_trace(["a", "b", "c", "d"], outcome=1.0) for _ in range(3)]
        result2 = sd2.analyze_traces(long_traces)
        # All discovered skills should have exactly 2 tools
        for skill in result2:
            assert len(skill.tool_sequence) == 2

    def test_to_skill_manifests(self):
        """Verify manifest dict format has expected keys."""
        sd = SkillDiscovery(min_frequency=2, min_outcome=0.0)
        traces = [_make_trace(["calc", "save"], outcome=0.9) for _ in range(3)]
        sd.analyze_traces(traces)
        manifests = sd.to_skill_manifests()
        assert len(manifests) >= 1
        m = manifests[0]
        assert "name" in m
        assert "description" in m
        assert "steps" in m
        assert "metadata" in m
        assert m["metadata"]["auto_discovered"] is True
        assert m["metadata"]["frequency"] >= 2
        assert isinstance(m["steps"], list)
        for step in m["steps"]:
            assert "tool" in step
            assert "params" in step

    def test_sort_by_quality(self):
        """Higher frequency*outcome skills should come first."""
        sd = SkillDiscovery(min_frequency=2, min_outcome=0.0)
        # Group A: high freq, high outcome
        traces_a = [_make_trace(["alpha", "beta"], outcome=1.0) for _ in range(10)]
        # Group B: low freq, low outcome
        traces_b = [_make_trace(["gamma", "delta"], outcome=0.3) for _ in range(2)]
        result = sd.analyze_traces(traces_a + traces_b)
        assert len(result) >= 2
        # First should be the higher quality one
        assert result[0].name == "alpha_beta"
        q0 = result[0].frequency * result[0].avg_outcome
        q1 = result[1].frequency * result[1].avg_outcome
        assert q0 >= q1

    def test_dict_traces(self):
        """Test with dict-format traces instead of objects."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.5)
        traces = [
            _make_dict_trace(
                ["read", "compute", "write"],
                outcome=0.8,
                query=f"task {i}",
            )
            for i in range(4)
        ]
        result = sd.analyze_traces(traces)
        assert len(result) >= 1
        # At minimum, 2-tool subsequences should be found
        all_tools = []
        for skill in result:
            all_tools.extend(skill.tool_sequence)
        assert "read" in all_tools or "compute" in all_tools

    def test_example_inputs_captured(self):
        """Example queries should be stored (up to 3)."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.5)
        traces = [
            _make_trace(
                ["search", "summarize"],
                outcome=0.9,
                query=f"Find info about topic {i}",
            )
            for i in range(5)
        ]
        result = sd.analyze_traces(traces)
        assert len(result) >= 1
        skill = result[0]
        assert len(skill.example_inputs) > 0
        # Max 3 examples stored
        assert len(skill.example_inputs) <= 3
        assert all("Find info about topic" in q for q in skill.example_inputs)

    def test_enum_step_type(self):
        """Steps with enum-style step_type (has .value) should work."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.0)
        traces = []
        for i in range(4):
            steps = [
                _StepEnum(tool_name="tool_a"),
                _StepEnum(tool_name="tool_b"),
            ]
            traces.append(_Trace(query=f"q{i}", outcome=0.9, steps=steps))
        result = sd.analyze_traces(traces)
        assert len(result) >= 1
        names = [s.name for s in result]
        assert "tool_a_tool_b" in names
