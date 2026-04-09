"""Tests for jarvis bench skills CLI command (Plan 2B)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from openjarvis.cli import cli


class TestBenchSkillsCommand:
    def test_help(self) -> None:
        result = CliRunner().invoke(cli, ["bench", "skills", "--help"])
        assert result.exit_code == 0
        assert "condition" in result.output.lower()

    def test_runs_all_conditions_with_mocked_runner(self, tmp_path: Path) -> None:
        from openjarvis.evals.skill_benchmark import (
            ConditionComparison,
            ConditionResult,
            SkillBenchmarkConfig,
        )

        # Build a fake comparison the mocked runner will return
        fake_results = {
            cond: ConditionResult(
                condition=cond,
                seeds=[42],
                per_seed_pass_rate={42: 0.5},
                mean_pass_rate=0.5,
                stddev_pass_rate=0.0,
                per_task_results={},
                skill_invocation_counts={},
                total_tokens=10,
                total_runtime_seconds=1.0,
            )
            for cond in (
                "no_skills",
                "skills_on",
                "skills_optimized_dspy",
                "skills_optimized_gepa",
            )
        }
        fake_cmp = ConditionComparison(
            config=SkillBenchmarkConfig(output_dir=tmp_path),
            started_at="2026-04-08T00:00:00Z",
            ended_at="2026-04-08T00:01:00Z",
            results=fake_results,
            deltas={"skills_on - no_skills": 0.0},
        )

        with patch(
            "openjarvis.evals.skill_benchmark.SkillBenchmarkRunner.run_all_conditions",
            return_value=fake_cmp,
        ):
            with patch(
                "openjarvis.evals.skill_benchmark.SkillBenchmarkRunner.write_report",
                return_value=tmp_path / "fake-report.md",
            ):
                result = CliRunner().invoke(
                    cli,
                    [
                        "bench",
                        "skills",
                        "--max-samples",
                        "1",
                        "--seeds",
                        "42",
                        "--output-dir",
                        str(tmp_path),
                    ],
                )
                assert result.exit_code == 0, result.output
                assert "no_skills" in result.output
                assert "skills_optimized_dspy" in result.output

    def test_runs_single_condition(self, tmp_path: Path) -> None:
        from openjarvis.evals.skill_benchmark import ConditionResult

        fake_result = ConditionResult(
            condition="skills_optimized_dspy",
            seeds=[42],
            per_seed_pass_rate={42: 0.7},
            mean_pass_rate=0.7,
            stddev_pass_rate=0.0,
            per_task_results={},
            skill_invocation_counts={},
            total_tokens=20,
            total_runtime_seconds=2.0,
        )

        with patch(
            "openjarvis.evals.skill_benchmark.SkillBenchmarkRunner.run_condition",
            return_value=fake_result,
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "bench",
                    "skills",
                    "--condition",
                    "skills_optimized_dspy",
                    "--seeds",
                    "42",
                    "--max-samples",
                    "1",
                    "--output-dir",
                    str(tmp_path),
                ],
            )
            assert result.exit_code == 0, result.output
            assert "skills_optimized_dspy" in result.output
            assert "0.700" in result.output or "0.7" in result.output
