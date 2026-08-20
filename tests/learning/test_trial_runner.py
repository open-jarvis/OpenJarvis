"""Tests for openjarvis.optimize.trial_runner module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openjarvis.evals.core.types import RunConfig, RunSummary
from openjarvis.learning.optimize.trial_runner import TrialRunner
from openjarvis.learning.optimize.types import TrialConfig, TrialResult


class TestTrialRunnerInit:
    """TrialRunner.__init__ stores parameters correctly."""

    def test_default_params(self) -> None:
        runner = TrialRunner(benchmark="supergpqa")
        assert runner.benchmark == "supergpqa"
        assert runner.max_samples == 50
        assert runner.judge_model == "gpt-5-mini-2025-08-07"
        assert runner.output_dir == "results/optimize/"

    def test_custom_params(self) -> None:
        runner = TrialRunner(
            benchmark="gaia",
            max_samples=100,
            judge_model="custom-judge",
            output_dir="/tmp/results/",
        )
        assert runner.benchmark == "gaia"
        assert runner.max_samples == 100
        assert runner.judge_model == "custom-judge"
        assert runner.output_dir == "/tmp/results/"


class TestBuildRunConfig:
    """TrialRunner._build_run_config maps recipe fields correctly."""

    def test_model_mapping(self) -> None:
        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(
            trial_id="t1",
            params={"intelligence.model": "qwen3:8b"},
        )
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert isinstance(cfg, RunConfig)
        assert cfg.model == "qwen3:8b"
        assert cfg.benchmark == "supergpqa"

    def test_agent_maps_to_agent_backend(self) -> None:
        runner = TrialRunner(benchmark="gaia")
        trial = TrialConfig(
            trial_id="t2",
            params={
                "intelligence.model": "llama3.1:8b",
                "agent.type": "native_react",
            },
        )
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.backend == "jarvis-agent"
        assert cfg.agent_name == "native_react"

    def test_no_agent_maps_to_direct_backend(self) -> None:
        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(
            trial_id="t3",
            params={"intelligence.model": "qwen3:8b"},
        )
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.backend == "jarvis-direct"
        assert cfg.agent_name is None

    def test_tools_mapping(self) -> None:
        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(
            trial_id="t4",
            params={
                "agent.type": "orchestrator",
                "tools.tool_set": ["calculator", "think"],
            },
        )
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.tools == ["calculator", "think"]

    def test_temperature_mapping(self) -> None:
        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(
            trial_id="t5",
            params={"intelligence.temperature": 0.7},
        )
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.temperature == 0.7

    def test_engine_key_mapping(self) -> None:
        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(
            trial_id="t6",
            params={"engine.backend": "vllm"},
        )
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.engine_key == "vllm"

    def test_max_samples_from_runner(self) -> None:
        runner = TrialRunner(benchmark="supergpqa", max_samples=25)
        trial = TrialConfig(trial_id="t7")
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.max_samples == 25

    def test_judge_model_from_runner(self) -> None:
        runner = TrialRunner(benchmark="supergpqa", judge_model="my-judge")
        trial = TrialConfig(trial_id="t8")
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.judge_model == "my-judge"

    def test_output_path_contains_trial_id(self) -> None:
        runner = TrialRunner(benchmark="supergpqa", output_dir="out/")
        trial = TrialConfig(
            trial_id="trial-abc",
            params={"intelligence.model": "qwen3:8b"},
        )
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert "trial-abc" in cfg.output_path
        assert cfg.output_path.startswith("out/")

    def test_default_model_fallback(self) -> None:
        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(trial_id="t9")
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.model == "default"

    def test_default_temperature_fallback(self) -> None:
        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(trial_id="t10")
        recipe = trial.to_recipe()
        cfg = runner._build_run_config(trial, recipe)

        assert cfg.temperature == 0.0


class TestRunTrial:
    """TrialRunner.run_trial integration (all eval deps mocked)."""

    def _make_summary(self, **overrides) -> RunSummary:
        defaults = dict(
            benchmark="supergpqa",
            category="reasoning",
            backend="jarvis-direct",
            model="qwen3:8b",
            total_samples=50,
            scored_samples=48,
            correct=40,
            accuracy=0.8333,
            errors=2,
            mean_latency_seconds=1.5,
            total_cost_usd=0.10,
            total_energy_joules=500.0,
            total_input_tokens=10000,
            total_output_tokens=5000,
        )
        defaults.update(overrides)
        return RunSummary(**defaults)

    @patch("openjarvis.evals.cli._build_scorer")
    @patch("openjarvis.evals.cli._build_judge_backend")
    @patch("openjarvis.evals.cli._build_dataset")
    @patch("openjarvis.evals.cli._build_backend")
    @patch("openjarvis.evals.core.runner.EvalRunner")
    def test_run_trial_returns_trial_result(
        self,
        mock_runner_cls,
        mock_build_backend,
        mock_build_dataset,
        mock_build_judge,
        mock_build_scorer,
    ) -> None:
        summary = self._make_summary()
        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = summary
        mock_runner_cls.return_value = mock_runner_instance

        mock_backend = MagicMock()
        mock_build_backend.return_value = mock_backend
        mock_judge = MagicMock()
        mock_build_judge.return_value = mock_judge

        runner = TrialRunner(benchmark="supergpqa", max_samples=50)
        trial = TrialConfig(
            trial_id="t-run",
            params={"intelligence.model": "qwen3:8b"},
        )

        result = runner.run_trial(trial)

        assert isinstance(result, TrialResult)
        assert result.trial_id == "t-run"
        assert result.config is trial
        mock_runner_cls.assert_called_once()
        mock_runner_instance.run.assert_called_once()

    @patch("openjarvis.evals.cli._build_scorer")
    @patch("openjarvis.evals.cli._build_judge_backend")
    @patch("openjarvis.evals.cli._build_dataset")
    @patch("openjarvis.evals.cli._build_backend")
    @patch("openjarvis.evals.core.runner.EvalRunner")
    def test_run_trial_accuracy_from_summary(
        self,
        mock_runner_cls,
        mock_build_backend,
        mock_build_dataset,
        mock_build_judge,
        mock_build_scorer,
    ) -> None:
        summary = self._make_summary(accuracy=0.92)
        mock_runner_cls.return_value.run.return_value = summary
        mock_build_backend.return_value = MagicMock()
        mock_build_judge.return_value = MagicMock()

        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(trial_id="t-acc", params={})
        result = runner.run_trial(trial)

        assert result.accuracy == 0.92

    @patch("openjarvis.evals.cli._build_scorer")
    @patch("openjarvis.evals.cli._build_judge_backend")
    @patch("openjarvis.evals.cli._build_dataset")
    @patch("openjarvis.evals.cli._build_backend")
    @patch("openjarvis.evals.core.runner.EvalRunner")
    def test_run_trial_tokens_summed(
        self,
        mock_runner_cls,
        mock_build_backend,
        mock_build_dataset,
        mock_build_judge,
        mock_build_scorer,
    ) -> None:
        summary = self._make_summary(
            total_input_tokens=3000,
            total_output_tokens=2000,
        )
        mock_runner_cls.return_value.run.return_value = summary
        mock_build_backend.return_value = MagicMock()
        mock_build_judge.return_value = MagicMock()

        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(trial_id="t-tok", params={})
        result = runner.run_trial(trial)

        assert result.total_tokens == 5000

    @patch("openjarvis.evals.cli._build_scorer")
    @patch("openjarvis.evals.cli._build_judge_backend")
    @patch("openjarvis.evals.cli._build_dataset")
    @patch("openjarvis.evals.cli._build_backend")
    @patch("openjarvis.evals.core.runner.EvalRunner")
    def test_run_trial_summary_attached(
        self,
        mock_runner_cls,
        mock_build_backend,
        mock_build_dataset,
        mock_build_judge,
        mock_build_scorer,
    ) -> None:
        summary = self._make_summary()
        mock_runner_cls.return_value.run.return_value = summary
        mock_build_backend.return_value = MagicMock()
        mock_build_judge.return_value = MagicMock()

        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(trial_id="t-sum", params={})
        result = runner.run_trial(trial)

        assert result.summary is summary

    @patch("openjarvis.evals.cli._build_scorer")
    @patch("openjarvis.evals.cli._build_judge_backend")
    @patch("openjarvis.evals.cli._build_dataset")
    @patch("openjarvis.evals.cli._build_backend")
    @patch("openjarvis.evals.core.runner.EvalRunner")
    def test_run_trial_failure_modes_on_errors(
        self,
        mock_runner_cls,
        mock_build_backend,
        mock_build_dataset,
        mock_build_judge,
        mock_build_scorer,
    ) -> None:
        summary = self._make_summary(errors=5)
        mock_runner_cls.return_value.run.return_value = summary
        mock_build_backend.return_value = MagicMock()
        mock_build_judge.return_value = MagicMock()

        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(trial_id="t-err", params={})
        result = runner.run_trial(trial)

        assert len(result.failure_modes) == 1
        assert "5" in result.failure_modes[0]

    @patch("openjarvis.evals.cli._build_scorer")
    @patch("openjarvis.evals.cli._build_judge_backend")
    @patch("openjarvis.evals.cli._build_dataset")
    @patch("openjarvis.evals.cli._build_backend")
    @patch("openjarvis.evals.core.runner.EvalRunner")
    def test_run_trial_no_failure_modes_when_clean(
        self,
        mock_runner_cls,
        mock_build_backend,
        mock_build_dataset,
        mock_build_judge,
        mock_build_scorer,
    ) -> None:
        summary = self._make_summary(errors=0)
        mock_runner_cls.return_value.run.return_value = summary
        mock_build_backend.return_value = MagicMock()
        mock_build_judge.return_value = MagicMock()

        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(trial_id="t-ok", params={})
        result = runner.run_trial(trial)

        assert result.failure_modes == []

    @patch("openjarvis.evals.cli._build_scorer")
    @patch("openjarvis.evals.cli._build_judge_backend")
    @patch("openjarvis.evals.cli._build_dataset")
    @patch("openjarvis.evals.cli._build_backend")
    @patch("openjarvis.evals.core.runner.EvalRunner")
    def test_run_trial_closes_backends(
        self,
        mock_runner_cls,
        mock_build_backend,
        mock_build_dataset,
        mock_build_judge,
        mock_build_scorer,
    ) -> None:
        summary = self._make_summary()
        mock_runner_cls.return_value.run.return_value = summary
        mock_backend = MagicMock()
        mock_build_backend.return_value = mock_backend
        mock_judge = MagicMock()
        mock_build_judge.return_value = mock_judge

        runner = TrialRunner(benchmark="supergpqa")
        trial = TrialConfig(trial_id="t-close", params={})
        runner.run_trial(trial)

        mock_backend.close.assert_called_once()
        mock_judge.close.assert_called_once()

    @patch("openjarvis.evals.cli._build_scorer")
    @patch("openjarvis.evals.cli._build_judge_backend")
    @patch("openjarvis.evals.cli._build_dataset")
    @patch("openjarvis.evals.cli._build_backend")
    @patch("openjarvis.evals.core.runner.EvalRunner")
    def test_run_trial_populates_sample_scores(
        self,
        mock_runner_cls,
        mock_build_backend,
        mock_build_dataset,
        mock_build_judge,
        mock_build_scorer,
    ) -> None:
        from openjarvis.evals.core.types import EvalResult

        summary = self._make_summary()
        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = summary
        # Mock the results property to return sample-level results
        mock_runner_instance.results = [
            EvalResult(
                record_id="r1",
                model_answer="42",
                is_correct=True,
                score=1.0,
                latency_seconds=0.5,
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.001,
            ),
            EvalResult(
                record_id="r2",
                model_answer="wrong",
                is_correct=False,
                score=0.0,
                latency_seconds=1.2,
                prompt_tokens=120,
                completion_tokens=60,
                cost_usd=0.002,
                error="parse error",
            ),
        ]
        mock_runner_cls.return_value = mock_runner_instance
        mock_build_backend.return_value = MagicMock()
        mock_build_judge.return_value = MagicMock()

        runner = TrialRunner(benchmark="supergpqa", max_samples=50)
        trial = TrialConfig(
            trial_id="t-scores",
            params={"intelligence.model": "qwen3:8b"},
        )
        result = runner.run_trial(trial)

        assert len(result.sample_scores) == 2
        assert result.sample_scores[0].record_id == "r1"
        assert result.sample_scores[0].is_correct is True
        assert result.sample_scores[0].latency_seconds == 0.5
        assert result.sample_scores[1].record_id == "r2"
        assert result.sample_scores[1].is_correct is False
        assert result.sample_scores[1].error == "parse error"
