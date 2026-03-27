"""TrialRunner -- evaluates a proposed config against a benchmark."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.evals.core.types import RunConfig, RunSummary
from openjarvis.learning.optimize.types import (
    BenchmarkScore,
    SampleScore,
    TrialConfig,
    TrialResult,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BenchmarkSpec:
    """Specification for one benchmark in a multi-benchmark optimization."""

    benchmark: str
    max_samples: int = 200
    weight: float = 1.0


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
            self.benchmark,
            judge_backend,
            run_config.judge_model,
        )

        try:
            eval_runner = EvalRunner(
                run_config,
                dataset,
                backend,
                scorer,
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

        max_tokens = recipe.max_tokens if recipe.max_tokens is not None else 2048

        return RunConfig(
            benchmark=self.benchmark,
            backend=backend_name,
            model=model,
            max_samples=self.max_samples,
            temperature=recipe.temperature if recipe.temperature is not None else 0.0,
            max_tokens=max_tokens,
            judge_model=self.judge_model,
            engine_key=recipe.engine_key,
            agent_name=recipe.agent_type,
            tools=list(recipe.tools) if recipe.tools else [],
            output_path=output_path,
            system_prompt=recipe.system_prompt or "",
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


class MultiBenchTrialRunner:
    """Evaluates a proposed config across multiple benchmarks.

    Delegates to :class:`TrialRunner` per benchmark, then aggregates
    results into a single composite :class:`TrialResult` with weighted
    metrics and per-benchmark breakdowns.
    """

    def __init__(
        self,
        benchmark_specs: List[BenchmarkSpec],
        judge_model: str = "gpt-5-mini-2025-08-07",
        output_dir: str = "results/optimize/",
    ) -> None:
        self.benchmark_specs = benchmark_specs
        self.judge_model = judge_model
        self.output_dir = output_dir

    def run_trial(self, trial: TrialConfig) -> TrialResult:
        """Run *trial* against all benchmarks and return a composite result."""
        per_benchmark: List[BenchmarkScore] = []

        for spec in self.benchmark_specs:
            if spec.benchmark == "terminalbench-native":
                score = self._run_terminalbench_native(trial, spec)
            else:
                runner = TrialRunner(
                    benchmark=spec.benchmark,
                    max_samples=spec.max_samples,
                    judge_model=self.judge_model,
                    output_dir=self.output_dir,
                )
                result = runner.run_trial(trial)
                score = BenchmarkScore(
                    benchmark=spec.benchmark,
                    accuracy=result.accuracy,
                    mean_latency_seconds=result.mean_latency_seconds,
                    total_cost_usd=result.total_cost_usd,
                    total_energy_joules=result.total_energy_joules,
                    total_tokens=result.total_tokens,
                    samples_evaluated=result.samples_evaluated,
                    errors=len([s for s in result.sample_scores if s.error]),
                    weight=spec.weight,
                    summary=result.summary,
                    sample_scores=result.sample_scores,
                )
            per_benchmark.append(score)

        return self._aggregate(trial, per_benchmark)

    def _run_terminalbench_native(
        self,
        trial: TrialConfig,
        spec: BenchmarkSpec,
    ) -> BenchmarkScore:
        """Run terminal-bench natively via Harness with Docker execution."""
        import time

        from terminal_bench import BenchmarkResults, Harness

        recipe = trial.to_recipe()
        model_name = recipe.model or "default"

        # For vLLM-served models, use openai/ prefix for litellm
        if recipe.engine_key == "vllm":
            litellm_model = f"openai/{model_name}"
            api_base = "http://localhost:8000/v1"
        else:
            litellm_model = model_name
            api_base = "http://localhost:8000/v1"

        temperature = recipe.temperature if recipe.temperature is not None else 0.2

        output_path = Path(self.output_dir) / f"terminalbench/{trial.trial_id}"
        output_path.mkdir(parents=True, exist_ok=True)

        harness_kwargs = {
            "output_path": output_path,
            "run_id": trial.trial_id,
            "dataset_name": "terminal-bench-core",
            "dataset_version": "0.1.1",
            "model_name": litellm_model,
            "agent_import_path": (
                "openjarvis.evals.backends.tb_agent:OpenJarvisTerminalBenchAgent"
            ),
            "agent_kwargs": {
                "model_name": litellm_model,
                "api_base": api_base,
                "temperature": temperature,
            },
            "n_concurrent_trials": 4,
            "cleanup": True,
        }

        if spec.max_samples and spec.max_samples < 200:
            harness_kwargs["n_tasks"] = spec.max_samples

        LOGGER.info(
            "Running terminal-bench native: model=%s, max_tasks=%s",
            litellm_model,
            spec.max_samples,
        )

        t0 = time.monotonic()
        try:
            harness = Harness(**harness_kwargs)
            tb_results: BenchmarkResults = harness.run()
        except Exception as e:
            LOGGER.error("terminal-bench harness failed: %s", e)
            return BenchmarkScore(
                benchmark="terminalbench-native",
                accuracy=0.0,
                mean_latency_seconds=0.0,
                samples_evaluated=0,
                errors=1,
                weight=spec.weight,
            )
        elapsed = time.monotonic() - t0

        # Extract results
        total_tasks = len(tb_results.results)
        resolved = sum(1 for r in tb_results.results if r.is_resolved)
        accuracy = resolved / total_tasks if total_tasks > 0 else 0.0
        mean_latency = elapsed / total_tasks if total_tasks > 0 else 0.0

        total_input = sum(r.total_input_tokens or 0 for r in tb_results.results)
        total_output = sum(r.total_output_tokens or 0 for r in tb_results.results)

        # Build sample scores
        sample_scores = []
        for r in tb_results.results:
            sample_scores.append(
                SampleScore(
                    record_id=f"terminalbench-native-{r.task_id}",
                    is_correct=bool(r.is_resolved),
                    score=1.0 if r.is_resolved else 0.0,
                    prompt_tokens=r.total_input_tokens or 0,
                    completion_tokens=r.total_output_tokens or 0,
                )
            )

        LOGGER.info(
            "terminal-bench native: %d/%d resolved (%.1f%%), %.1fs total",
            resolved,
            total_tasks,
            accuracy * 100,
            elapsed,
        )

        return BenchmarkScore(
            benchmark="terminalbench-native",
            accuracy=accuracy,
            mean_latency_seconds=mean_latency,
            total_tokens=total_input + total_output,
            samples_evaluated=total_tasks,
            errors=sum(
                1
                for r in tb_results.results
                if r.failure_mode.value not in ("none", "unset")
            ),
            weight=spec.weight,
            sample_scores=sample_scores,
        )

    @staticmethod
    def _aggregate(
        trial: TrialConfig,
        per_benchmark: List[BenchmarkScore],
    ) -> TrialResult:
        """Compute weighted-aggregate metrics from per-benchmark scores."""
        total_weight = sum(b.weight for b in per_benchmark) or 1.0
        accuracy = sum(b.accuracy * b.weight for b in per_benchmark) / total_weight

        # Weighted mean latency by samples evaluated
        total_samples = sum(b.samples_evaluated for b in per_benchmark) or 1
        mean_latency = (
            sum(b.mean_latency_seconds * b.samples_evaluated for b in per_benchmark)
            / total_samples
        )

        # Sums across benchmarks
        total_cost = sum(b.total_cost_usd for b in per_benchmark)
        total_energy = sum(b.total_energy_joules for b in per_benchmark)
        total_tokens = sum(b.total_tokens for b in per_benchmark)

        # Merge all sample scores
        all_scores: List[SampleScore] = []
        failure_modes: List[str] = []
        for b in per_benchmark:
            all_scores.extend(b.sample_scores)
            if b.errors > 0:
                failure_modes.append(f"{b.benchmark}: {b.errors} errors")

        return TrialResult(
            trial_id=trial.trial_id,
            config=trial,
            accuracy=accuracy,
            mean_latency_seconds=mean_latency,
            total_cost_usd=total_cost,
            total_energy_joules=total_energy,
            total_tokens=total_tokens,
            samples_evaluated=total_samples,
            failure_modes=failure_modes,
            sample_scores=all_scores,
            per_benchmark=per_benchmark,
        )


__all__ = ["BenchmarkSpec", "MultiBenchTrialRunner", "TrialRunner"]
