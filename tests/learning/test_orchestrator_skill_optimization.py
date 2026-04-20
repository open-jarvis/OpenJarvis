"""Tests for LearningOrchestrator opt-in skill optimization (Plan 2A)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestOrchestratorSkillAutoOptimize:
    def test_auto_optimize_disabled_by_default_does_not_call_skill_optimizer(
        self, tmp_path: Path
    ) -> None:
        from openjarvis.learning.learning_orchestrator import (
            LearningOrchestrator,
        )

        store = MagicMock()
        store.list_traces.return_value = []

        orchestrator = LearningOrchestrator(
            trace_store=store,
            config_dir=tmp_path,
        )

        with patch(
            "openjarvis.learning.agents.skill_optimizer.SkillOptimizer.optimize"
        ) as mock_optimize:
            orchestrator._maybe_optimize_skills(auto_optimize=False)
            mock_optimize.assert_not_called()

    def test_auto_optimize_enabled_calls_skill_optimizer(self, tmp_path: Path) -> None:
        from openjarvis.learning.learning_orchestrator import (
            LearningOrchestrator,
        )

        store = MagicMock()
        store.list_traces.return_value = []

        orchestrator = LearningOrchestrator(
            trace_store=store,
            config_dir=tmp_path,
        )

        with patch(
            "openjarvis.learning.agents.skill_optimizer.SkillOptimizer.optimize",
            return_value={},
        ) as mock_optimize:
            orchestrator._maybe_optimize_skills(
                auto_optimize=True,
                optimizer="dspy",
                min_traces_per_skill=5,
            )
            mock_optimize.assert_called_once()


class TestOrchestratorRunSkillTrigger:
    """End-to-end: LearningOrchestrator.run() invokes _maybe_optimize_skills
    when learning.skills.auto_optimize is true (Plan 2A C2 fix)."""

    def _make_store(self) -> MagicMock:
        store = MagicMock()
        # Just enough surface area for orchestrator.run() to short-circuit
        store.list_traces.return_value = []
        return store

    def _make_config(self, *, auto_optimize: bool):
        from openjarvis.core.config import (
            JarvisConfig,
            LearningConfig,
            SkillsLearningConfig,
        )

        cfg = JarvisConfig()
        cfg.learning = LearningConfig()
        cfg.learning.skills = SkillsLearningConfig(
            auto_optimize=auto_optimize,
            optimizer="dspy",
            min_traces_per_skill=5,
        )
        return cfg

    def test_run_does_not_call_skill_optimizer_when_disabled(
        self, tmp_path: Path
    ) -> None:
        from openjarvis.learning.learning_orchestrator import (
            LearningOrchestrator,
        )

        store = self._make_store()
        orchestrator = LearningOrchestrator(
            trace_store=store,
            config_dir=tmp_path,
        )

        with patch(
            "openjarvis.core.config.load_config",
            return_value=self._make_config(auto_optimize=False),
        ):
            with patch(
                "openjarvis.learning.agents.skill_optimizer.SkillOptimizer.optimize"
            ) as mock_optimize:
                orchestrator.run()
                mock_optimize.assert_not_called()

    def test_run_calls_skill_optimizer_when_enabled(
        self, tmp_path: Path
    ) -> None:
        from openjarvis.learning.agents.skill_optimizer import (
            SkillOptimizationResult,
        )
        from openjarvis.learning.learning_orchestrator import (
            LearningOrchestrator,
        )

        store = self._make_store()
        orchestrator = LearningOrchestrator(
            trace_store=store,
            config_dir=tmp_path,
        )

        fake_results = {
            "research-skill": SkillOptimizationResult(
                skill_name="research-skill",
                status="optimized",
                trace_count=10,
            ),
        }

        with patch(
            "openjarvis.core.config.load_config",
            return_value=self._make_config(auto_optimize=True),
        ):
            with patch(
                "openjarvis.learning.agents.skill_optimizer.SkillOptimizer.optimize",
                return_value=fake_results,
            ) as mock_optimize:
                result = orchestrator.run()
                mock_optimize.assert_called_once()
                # The orchestrator should record the skill optimization
                # results in the returned dict
                assert "skill_optimization" in result
                assert "research-skill" in result["skill_optimization"]
                assert (
                    result["skill_optimization"]["research-skill"]["status"]
                    == "optimized"
                )
