"""Tests for jarvis optimize skills CLI command (Plan 2A)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from openjarvis.cli import cli


class TestOptimizeSkillsCommand:
    def test_help(self) -> None:
        result = CliRunner().invoke(cli, ["optimize", "skills", "--help"])
        assert result.exit_code == 0

    def test_dry_run_no_traces(self, tmp_path: Path) -> None:
        class _EmptyStore:
            def list_traces(self, *, limit: int = 100, **kwargs):
                return []

        with patch(
            "openjarvis.cli.optimize_cmd._get_trace_store",
            return_value=_EmptyStore(),
        ):
            result = CliRunner().invoke(cli, ["optimize", "skills", "--dry-run"])
            assert result.exit_code == 0

    def test_optimize_runs_with_mocked_optimizer(self, tmp_path: Path) -> None:
        from openjarvis.core.types import StepType, Trace, TraceStep
        from openjarvis.learning.agents.skill_optimizer import (
            SkillOptimizationResult,
        )

        def _trace(skill_name="research-skill"):
            return Trace(
                query=f"q for {skill_name}",
                steps=[
                    TraceStep(
                        step_type=StepType.TOOL_CALL,
                        timestamp=0.0,
                        input={"tool": f"skill_{skill_name}", "arguments": {}},
                        output={"success": True, "result": "ok"},
                        metadata={
                            "skill": skill_name,
                            "skill_kind": "instructional",
                        },
                    ),
                ],
                outcome="success",
                feedback=1.0,
                result="ok",
            )

        class _Store:
            def list_traces(self, *, limit: int = 100, **kwargs):
                return [_trace() for _ in range(25)]

        fake_results = {
            "research-skill": SkillOptimizationResult(
                skill_name="research-skill",
                status="optimized",
                trace_count=25,
                overlay_path=tmp_path / "research-skill" / "optimized.toml",
            ),
        }

        with patch(
            "openjarvis.cli.optimize_cmd._get_trace_store",
            return_value=_Store(),
        ):
            with patch(
                "openjarvis.learning.agents.skill_optimizer.SkillOptimizer.optimize",
                return_value=fake_results,
            ):
                result = CliRunner().invoke(
                    cli, ["optimize", "skills", "--policy", "dspy"]
                )
                assert result.exit_code == 0
                assert "research-skill" in result.output
                assert "optimized" in result.output
