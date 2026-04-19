"""Tests for SkillManager.discover_from_traces (Plan 2A)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from openjarvis.core.events import EventBus
from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.skills.manager import SkillManager


class _FakeTraceStore:
    """In-memory trace store stub for tests."""

    def __init__(self, traces: List[Trace]) -> None:
        self._traces = traces

    def list_traces(self, *, limit: int = 100, **_kwargs: Any) -> List[Trace]:
        return list(self._traces[:limit])


def _make_trace(tools: List[str], outcome: str = "success") -> Trace:
    steps = [
        TraceStep(
            step_type=StepType.TOOL_CALL,
            timestamp=0.0,
            input={"tool": tool, "arguments": {}},
            output={"success": True, "result": ""},
            metadata={},
        )
        for tool in tools
    ]
    return Trace(
        query="test query",
        agent="native_react",
        model="qwen3.5:9b",
        engine="ollama",
        steps=steps,
        outcome=outcome,
        feedback=1.0 if outcome == "success" else 0.0,
    )


class TestDiscoverFromTraces:
    def test_writes_manifest_for_recurring_sequence(self, tmp_path: Path):
        # Five identical successful traces of (web_search, calculator)
        traces = [_make_trace(["web_search", "calculator"]) for _ in range(5)]
        store = _FakeTraceStore(traces)

        mgr = SkillManager(bus=EventBus())
        output_dir = tmp_path / "discovered"
        written = mgr.discover_from_traces(
            store, min_frequency=3, output_dir=output_dir
        )

        assert len(written) >= 1
        # Discovery should produce at least one manifest file
        assert any(Path(item["path"]).exists() for item in written)

    def test_respects_min_frequency_filter(self, tmp_path: Path):
        # Only 2 occurrences — below default min_frequency of 3
        traces = [_make_trace(["web_search", "calculator"]) for _ in range(2)]
        store = _FakeTraceStore(traces)

        mgr = SkillManager(bus=EventBus())
        output_dir = tmp_path / "discovered"
        written = mgr.discover_from_traces(
            store, min_frequency=3, output_dir=output_dir
        )

        assert written == []

    def test_empty_trace_store_returns_empty_list(self, tmp_path: Path):
        store = _FakeTraceStore([])
        mgr = SkillManager(bus=EventBus())
        output_dir = tmp_path / "discovered"
        written = mgr.discover_from_traces(store, output_dir=output_dir)
        assert written == []

    def test_discovered_skills_use_hyphen_naming(self, tmp_path: Path):
        traces = [_make_trace(["web_search", "calculator"]) for _ in range(5)]
        store = _FakeTraceStore(traces)

        mgr = SkillManager(bus=EventBus())
        output_dir = tmp_path / "discovered"
        written = mgr.discover_from_traces(
            store, min_frequency=3, output_dir=output_dir
        )

        for item in written:
            name = item["name"]
            # Plan 1 spec: lowercase, only hyphens (no underscores)
            assert name == name.lower()
            assert "_" not in name

    def test_round_trip_discover_then_load(self, tmp_path: Path):
        """Discovered skills are subsequently loadable via discover()."""
        traces = [_make_trace(["web_search", "calculator"]) for _ in range(5)]
        store = _FakeTraceStore(traces)

        mgr = SkillManager(bus=EventBus())
        output_dir = tmp_path / "discovered"
        mgr.discover_from_traces(store, min_frequency=3, output_dir=output_dir)

        # Now load them
        mgr2 = SkillManager(bus=EventBus())
        mgr2.discover(paths=[output_dir])
        # At least one of the discovered skills should be loadable
        names = mgr2.skill_names()
        assert len(names) >= 1
