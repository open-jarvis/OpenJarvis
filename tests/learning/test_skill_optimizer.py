"""Tests for SkillOptimizer (Plan 2A) — buckets traces by skill, runs DSPy/GEPA."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from openjarvis.core.events import EventBus
from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.skills.manager import SkillManager


class _FakeTraceStore:
    def __init__(self, traces: List[Trace]) -> None:
        self._traces = traces

    def list_traces(self, *, limit: int = 100, **_kwargs: Any) -> List[Trace]:
        return list(self._traces[:limit])


def _make_skill_trace(skill_name: str, feedback: float = 1.0) -> Trace:
    return Trace(
        query=f"query for {skill_name}",
        agent="native_react",
        model="qwen3.5:9b",
        engine="ollama",
        steps=[
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=0.0,
                input={"tool": f"skill_{skill_name}", "arguments": {}},
                output={"success": True, "result": "ok"},
                metadata={"skill": skill_name, "skill_kind": "instructional"},
            ),
        ],
        outcome="success",
        feedback=feedback,
        result="result text",
    )


def _make_manager_with_skill(name: str, tmp_path: Path) -> SkillManager:
    skill_dir = tmp_path / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Original description\n---\nBody"
    )
    mgr = SkillManager(bus=EventBus())
    mgr.discover(paths=[tmp_path / "skills"])
    return mgr


class TestSkillOptimizerBucketing:
    def test_buckets_traces_by_skill_name(self, tmp_path: Path):
        from openjarvis.learning.agents.skill_optimizer import SkillOptimizer

        traces = [
            _make_skill_trace("research-skill"),
            _make_skill_trace("research-skill"),
            _make_skill_trace("code-skill"),
        ]
        optimizer = SkillOptimizer(min_traces_per_skill=1)
        buckets = optimizer._bucket_traces_by_skill(traces)

        assert "research-skill" in buckets
        assert "code-skill" in buckets
        assert len(buckets["research-skill"]) == 2
        assert len(buckets["code-skill"]) == 1

    def test_skips_traces_without_skill_metadata(self, tmp_path: Path):
        from openjarvis.learning.agents.skill_optimizer import SkillOptimizer

        # A trace with no skill metadata in the tool call
        plain_trace = Trace(
            query="plain",
            steps=[
                TraceStep(
                    step_type=StepType.TOOL_CALL,
                    timestamp=0.0,
                    input={"tool": "calculator", "arguments": {}},
                    output={"success": True, "result": "42"},
                    metadata={},
                ),
            ],
        )
        optimizer = SkillOptimizer(min_traces_per_skill=1)
        buckets = optimizer._bucket_traces_by_skill([plain_trace])
        assert buckets == {}


class TestSkillOptimizerOptimize:
    def test_skips_skills_below_min_traces(self, tmp_path: Path):
        from openjarvis.learning.agents.skill_optimizer import SkillOptimizer

        traces = [_make_skill_trace("research-skill") for _ in range(3)]
        store = _FakeTraceStore(traces)
        mgr = _make_manager_with_skill("research-skill", tmp_path)

        optimizer = SkillOptimizer(min_traces_per_skill=20)
        results = optimizer.optimize(store, mgr, overlay_dir=tmp_path / "overlays")

        assert "research-skill" in results
        assert results["research-skill"].status == "skipped"
        assert results["research-skill"].trace_count == 3

    def test_optimizes_skill_with_enough_traces(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from openjarvis.learning.agents.skill_optimizer import (
            SkillOptimizer,
            _OptimizerOutput,
        )

        traces = [_make_skill_trace("research-skill") for _ in range(25)]
        store = _FakeTraceStore(traces)
        mgr = _make_manager_with_skill("research-skill", tmp_path)

        # Mock the underlying DSPy call
        def fake_run(self_unused, skill_name, skill_traces):
            return _OptimizerOutput(
                description="An optimized description",
                few_shot=[
                    {"input": "hello", "output": "world"},
                ],
            )

        monkeypatch.setattr(SkillOptimizer, "_run_dspy", fake_run)

        optimizer = SkillOptimizer(min_traces_per_skill=10)
        results = optimizer.optimize(store, mgr, overlay_dir=tmp_path / "overlays")

        assert results["research-skill"].status == "optimized"
        assert results["research-skill"].trace_count == 25
        # Overlay file should exist
        overlay_path = tmp_path / "overlays" / "research-skill" / "optimized.toml"
        assert overlay_path.exists()
        # And contain the optimized description
        content = overlay_path.read_text()
        assert "An optimized description" in content
        assert "hello" in content
        assert "world" in content
