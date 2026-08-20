"""Tests for SkillBenchmarkRunner (Plan 2B)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


class TestSkillBenchmarkConfigDefaults:
    def test_defaults(self):
        from openjarvis.evals.skill_benchmark import SkillBenchmarkConfig

        cfg = SkillBenchmarkConfig()
        assert cfg.benchmark == "pinchbench"
        assert cfg.model == "qwen3.5:9b"
        assert cfg.engine == "ollama"
        assert cfg.agent == "native_react"
        assert cfg.seeds == [42, 43, 44]
        assert cfg.max_samples is None
        assert "shell_exec" in cfg.tools
        assert "web_search" in cfg.tools

    def test_construct_with_overrides(self):
        from openjarvis.evals.skill_benchmark import SkillBenchmarkConfig

        cfg = SkillBenchmarkConfig(
            benchmark="pinchbench",
            model="other-model",
            seeds=[1, 2],
            max_samples=5,
        )
        assert cfg.model == "other-model"
        assert cfg.seeds == [1, 2]
        assert cfg.max_samples == 5


class TestConditionResult:
    def test_create(self):
        from openjarvis.evals.skill_benchmark import ConditionResult

        r = ConditionResult(
            condition="no_skills",
            seeds=[42, 43, 44],
            per_seed_pass_rate={42: 0.30, 43: 0.32, 44: 0.28},
            mean_pass_rate=0.30,
            stddev_pass_rate=0.02,
            per_task_results={"task_001": [True, False, True]},
            skill_invocation_counts={},
            total_tokens=1000,
            total_runtime_seconds=120.0,
        )
        assert r.condition == "no_skills"
        assert r.mean_pass_rate == 0.30
        assert r.skill_invocation_counts == {}


class TestConditionComparison:
    def test_create(self):
        from openjarvis.evals.skill_benchmark import (
            ConditionComparison,
            ConditionResult,
            SkillBenchmarkConfig,
        )

        cfg = SkillBenchmarkConfig()
        cmp = ConditionComparison(
            config=cfg,
            started_at="2026-04-08T00:00:00Z",
            ended_at="2026-04-08T01:00:00Z",
            results={
                "no_skills": ConditionResult(
                    condition="no_skills",
                    seeds=[42],
                    per_seed_pass_rate={42: 0.30},
                    mean_pass_rate=0.30,
                    stddev_pass_rate=0.0,
                    per_task_results={},
                    skill_invocation_counts={},
                    total_tokens=0,
                    total_runtime_seconds=0.0,
                ),
            },
            deltas={},
        )
        assert "no_skills" in cmp.results
        assert cmp.config.benchmark == "pinchbench"


class TestBuildBackendForCondition:
    def _make_runner(self, tmp_path: Path):
        from openjarvis.evals.skill_benchmark import (
            SkillBenchmarkConfig,
            SkillBenchmarkRunner,
        )

        cfg = SkillBenchmarkConfig(
            engine="ollama",
            model="qwen3.5:9b",
            tools=[],
            seeds=[42],
            output_dir=tmp_path,
            overlay_dir_dspy=tmp_path / "dspy",
            overlay_dir_gepa=tmp_path / "gepa",
        )
        return SkillBenchmarkRunner(cfg)

    def test_unknown_condition_raises(self, tmp_path: Path):
        runner = self._make_runner(tmp_path)
        with pytest.raises(ValueError, match="condition"):
            runner._backend_kwargs_for_condition("not_a_condition")

    def test_no_skills_kwargs(self, tmp_path: Path):
        runner = self._make_runner(tmp_path)
        kw = runner._backend_kwargs_for_condition("no_skills")
        assert kw["skills_enabled"] is False
        assert kw["overlay_dir"] is None

    def test_skills_on_kwargs(self, tmp_path: Path):
        runner = self._make_runner(tmp_path)
        kw = runner._backend_kwargs_for_condition("skills_on")
        assert kw["skills_enabled"] is True
        # skills_on uses an empty/missing overlay dir so no overlays load
        assert kw["overlay_dir"] is not None
        assert "skills_on_empty_overlays" in str(kw["overlay_dir"])

    def test_skills_optimized_dspy_kwargs(self, tmp_path: Path):
        runner = self._make_runner(tmp_path)
        kw = runner._backend_kwargs_for_condition("skills_optimized_dspy")
        assert kw["skills_enabled"] is True
        assert kw["overlay_dir"] == tmp_path / "dspy"

    def test_skills_optimized_gepa_kwargs(self, tmp_path: Path):
        runner = self._make_runner(tmp_path)
        kw = runner._backend_kwargs_for_condition("skills_optimized_gepa")
        assert kw["skills_enabled"] is True
        assert kw["overlay_dir"] == tmp_path / "gepa"


class TestRunCondition:
    def _make_runner(self, tmp_path: Path):
        from openjarvis.evals.skill_benchmark import (
            SkillBenchmarkConfig,
            SkillBenchmarkRunner,
        )

        cfg = SkillBenchmarkConfig(
            seeds=[42, 43],
            max_samples=2,
            output_dir=tmp_path,
        )
        return SkillBenchmarkRunner(cfg)

    def test_run_condition_aggregates_per_seed(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """run_condition runs the eval once per seed and aggregates the
        results into a ConditionResult."""
        from openjarvis.evals.skill_benchmark import (
            SkillBenchmarkRunner,
        )

        runner = self._make_runner(tmp_path)

        # Stub _run_single_seed to return synthetic per-seed data
        seed_results = {
            42: {
                "pass_rate": 0.5,
                "per_task": {"task_001": True, "task_002": False},
                "skill_invocations": {"research-skill": 1},
                "total_tokens": 100,
                "total_runtime_seconds": 10.0,
            },
            43: {
                "pass_rate": 1.0,
                "per_task": {"task_001": True, "task_002": True},
                "skill_invocations": {"research-skill": 2},
                "total_tokens": 200,
                "total_runtime_seconds": 20.0,
            },
        }

        def fake_run_single_seed(self_unused, condition, seed):
            return seed_results[seed]

        monkeypatch.setattr(
            SkillBenchmarkRunner,
            "_run_single_seed",
            fake_run_single_seed,
        )

        result = runner.run_condition("no_skills")

        assert result.condition == "no_skills"
        assert result.seeds == [42, 43]
        assert result.per_seed_pass_rate == {42: 0.5, 43: 1.0}
        assert result.mean_pass_rate == 0.75
        assert result.stddev_pass_rate > 0.0
        # Per-task aggregation: each task gets a list of [seed1_pass, seed2_pass]
        assert result.per_task_results["task_001"] == [True, True]
        assert result.per_task_results["task_002"] == [False, True]
        # Skill invocation counts summed across seeds
        assert result.skill_invocation_counts["research-skill"] == 3
        assert result.total_tokens == 300
        assert result.total_runtime_seconds == 30.0

    def test_run_condition_single_seed_zero_stddev(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from openjarvis.evals.skill_benchmark import (
            SkillBenchmarkConfig,
            SkillBenchmarkRunner,
        )

        cfg = SkillBenchmarkConfig(
            seeds=[42],
            max_samples=1,
            output_dir=tmp_path,
        )
        runner = SkillBenchmarkRunner(cfg)

        def fake_run_single_seed(self_unused, condition, seed):
            return {
                "pass_rate": 0.42,
                "per_task": {"task_001": False},
                "skill_invocations": {},
                "total_tokens": 50,
                "total_runtime_seconds": 5.0,
            }

        monkeypatch.setattr(
            SkillBenchmarkRunner,
            "_run_single_seed",
            fake_run_single_seed,
        )

        result = runner.run_condition("no_skills")
        assert result.mean_pass_rate == 0.42
        # Single seed → stddev is 0
        assert result.stddev_pass_rate == 0.0


class TestRunAllConditions:
    def test_run_all_conditions_invokes_all_four(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from openjarvis.evals.skill_benchmark import (
            ConditionResult,
            SkillBenchmarkConfig,
            SkillBenchmarkRunner,
        )

        cfg = SkillBenchmarkConfig(
            seeds=[42],
            max_samples=1,
            output_dir=tmp_path,
        )
        runner = SkillBenchmarkRunner(cfg)

        invoked: list = []

        def fake_run_condition(self_unused, condition):
            invoked.append(condition)
            return ConditionResult(
                condition=condition,
                seeds=[42],
                per_seed_pass_rate={42: 0.5},
                mean_pass_rate=0.5,
                stddev_pass_rate=0.0,
                per_task_results={},
                skill_invocation_counts={},
                total_tokens=10,
                total_runtime_seconds=1.0,
            )

        monkeypatch.setattr(
            SkillBenchmarkRunner,
            "run_condition",
            fake_run_condition,
        )

        comparison = runner.run_all_conditions()
        assert set(invoked) == {
            "no_skills",
            "skills_on",
            "skills_optimized_dspy",
            "skills_optimized_gepa",
        }
        assert len(comparison.results) == 4

    def test_run_all_conditions_computes_deltas(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from openjarvis.evals.skill_benchmark import (
            ConditionResult,
            SkillBenchmarkConfig,
            SkillBenchmarkRunner,
        )

        cfg = SkillBenchmarkConfig(
            seeds=[42],
            max_samples=1,
            output_dir=tmp_path,
        )
        runner = SkillBenchmarkRunner(cfg)

        rates = {
            "no_skills": 0.30,
            "skills_on": 0.35,
            "skills_optimized_dspy": 0.40,
            "skills_optimized_gepa": 0.38,
        }

        def fake_run_condition(self_unused, condition):
            return ConditionResult(
                condition=condition,
                seeds=[42],
                per_seed_pass_rate={42: rates[condition]},
                mean_pass_rate=rates[condition],
                stddev_pass_rate=0.0,
                per_task_results={},
                skill_invocation_counts={},
                total_tokens=0,
                total_runtime_seconds=0.0,
            )

        monkeypatch.setattr(
            SkillBenchmarkRunner,
            "run_condition",
            fake_run_condition,
        )

        comparison = runner.run_all_conditions()
        # Deltas use the same names as the conditions
        assert comparison.deltas["skills_on - no_skills"] == pytest.approx(0.05)
        assert comparison.deltas["skills_optimized_dspy - skills_on"] == pytest.approx(
            0.05
        )
        assert comparison.deltas["skills_optimized_gepa - skills_on"] == pytest.approx(
            0.03
        )


class TestWriteReport:
    def test_write_report_creates_dated_markdown(self, tmp_path: Path) -> None:
        from openjarvis.evals.skill_benchmark import (
            ConditionComparison,
            ConditionResult,
            SkillBenchmarkConfig,
            SkillBenchmarkRunner,
        )

        cfg = SkillBenchmarkConfig(output_dir=tmp_path)
        runner = SkillBenchmarkRunner(cfg)

        result = ConditionResult(
            condition="no_skills",
            seeds=[42, 43],
            per_seed_pass_rate={42: 0.30, 43: 0.32},
            mean_pass_rate=0.31,
            stddev_pass_rate=0.014,
            per_task_results={"task_001": [True, False]},
            skill_invocation_counts={},
            total_tokens=100,
            total_runtime_seconds=12.5,
        )
        cmp = ConditionComparison(
            config=cfg,
            started_at="2026-04-08T00:00:00Z",
            ended_at="2026-04-08T00:01:00Z",
            results={"no_skills": result},
            deltas={},
        )

        path = runner.write_report(cmp)
        assert path.exists()
        assert path.suffix == ".md"
        content = path.read_text()
        assert "no_skills" in content
        assert "0.31" in content or "31.0" in content
        assert "task_001" in content
