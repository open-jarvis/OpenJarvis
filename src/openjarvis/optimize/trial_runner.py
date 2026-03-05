"""TrialRunner -- evaluates a proposed config against a benchmark."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.evals.core.types import RunConfig, RunSummary
from openjarvis.optimize.types import SampleScore, TrialConfig, TrialResult

LOGGER = logging.getLogger(__name__)


class TrialRunner:
    """Evaluates a proposed config against a benchmark.

    Bridges the optimization types (:class:`TrialConfig`) to the eval
    framework (:class:`EvalRunner`) so the optimizer can score candidate
    configurations end-to-end.
    """

    def __init__(
        self,
        benchmark: str,
        max_samples: int = 50,
        judge_model: str = "gpt-5-mini-2025-08-07",
        output_dir: str = "results/optimize/",
    ) -> None:
        self.benchmark = benchmark
        self.max_samples = max_samples
        self.judge_model = judge_model
        self.output_dir = output_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_trial(self, trial: TrialConfig) -> TrialResult:
        """Run *trial* against the configured benchmark and return a result.

        Steps:
        1. Convert ``trial`` to a :class:`Recipe` and extract params.
        2. Build a :class:`RunConfig` from recipe + benchmark settings.
        3. Lazily import eval-framework registries to resolve the
           benchmark -> dataset + scorer, and build the backend.
        4. Execute via ``EvalRunner.run()`` -> :class:`RunSummary`.
        5. Map the summary into a :class:`TrialResult`.
        """
        recipe = trial.to_recipe()
        run_config = self._build_run_config(trial, recipe)

        # Lazy imports so the optimize package stays lightweight
        from openjarvis.evals.cli import (
            _build_backend,
            _build_dataset,
            _build_judge_backend,
            _build_scorer,
        )
        from openjarvis.evals.core.runner import EvalRunner

        dataset = _build_dataset(self.benchmark)
        backend = _build_backend(
            run_config.backend,
            run_config.engine_key,
            run_config.agent_name or "orchestrator",
            run_config.tools,
        )
        judge_backend = _build_judge_backend(run_config.judge_model)
        scorer = _build_scorer(
            self.benchmark, judge_backend, run_config.judge_model,
        )

        try:
            eval_runner = EvalRunner(
                run_config, dataset, backend, scorer,
            )
            summary: RunSummary = eval_runner.run()
            eval_results = eval_runner.results
        finally:
            backend.close()
            judge_backend.close()

        return self._summary_to_result(trial, summary, eval_results=eval_results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_run_config(self, trial: TrialConfig, recipe: Any) -> RunConfig:
        """Map recipe fields into a :class:`RunConfig`."""
        model = recipe.model or "default"
        backend_name = "jarvis-direct"
        if recipe.agent_type is not None:
            backend_name = "jarvis-agent"

        model_slug = model.replace("/", "-").replace(":", "-")
        output_path = str(
            Path(self.output_dir) / f"{trial.trial_id}_{model_slug}.jsonl",
        )

        return RunConfig(
            benchmark=self.benchmark,
            backend=backend_name,
            model=model,
            max_samples=self.max_samples,
            temperature=recipe.temperature if recipe.temperature is not None else 0.0,
            judge_model=self.judge_model,
            engine_key=recipe.engine_key,
            agent_name=recipe.agent_type,
            tools=list(recipe.tools) if recipe.tools else [],
            output_path=output_path,
        )

    @staticmethod
    def _summary_to_result(
        trial: TrialConfig,
        summary: RunSummary,
        eval_results: Optional[List[Any]] = None,
    ) -> TrialResult:
        """Convert a :class:`RunSummary` to a :class:`TrialResult`."""
        total_tokens = summary.total_input_tokens + summary.total_output_tokens

        failure_modes: List[str] = []
        if summary.errors > 0:
            failure_modes.append(f"{summary.errors} evaluation errors")

        sample_scores: List[SampleScore] = []
        if eval_results:
            for er in eval_results:
                sample_scores.append(
                    SampleScore(
                        record_id=er.record_id,
                        is_correct=er.is_correct,
                        score=er.score,
                        latency_seconds=er.latency_seconds,
                        prompt_tokens=er.prompt_tokens,
                        completion_tokens=er.completion_tokens,
                        cost_usd=er.cost_usd,
                        error=er.error,
                        ttft=er.ttft,
                        energy_joules=er.energy_joules,
                        power_watts=er.power_watts,
                        gpu_utilization_pct=er.gpu_utilization_pct,
                        throughput_tok_per_sec=er.throughput_tok_per_sec,
                        mfu_pct=er.mfu_pct,
                        mbu_pct=er.mbu_pct,
                        ipw=er.ipw,
                        ipj=er.ipj,
                        energy_per_output_token_joules=er.energy_per_output_token_joules,
                        throughput_per_watt=er.throughput_per_watt,
                        mean_itl_ms=er.mean_itl_ms,
                    )
                )

        return TrialResult(
            trial_id=trial.trial_id,
            config=trial,
            accuracy=summary.accuracy,
            mean_latency_seconds=summary.mean_latency_seconds,
            total_cost_usd=summary.total_cost_usd,
            total_energy_joules=summary.total_energy_joules,
            total_tokens=total_tokens,
            samples_evaluated=summary.total_samples,
            failure_modes=failure_modes,
            summary=summary,
            sample_scores=sample_scores,
        )


__all__ = ["TrialRunner"]
