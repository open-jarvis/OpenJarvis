"""OptimizationEngine -- orchestrates the optimize loop.

Ties together the LLM optimizer, trial runner, and persistence store
into a single propose -> evaluate -> analyze -> repeat loop.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import tomli_w
except ModuleNotFoundError:  # pragma: no cover
    tomli_w = None  # type: ignore[assignment]

from openjarvis.learning.optimize.llm_optimizer import LLMOptimizer
from openjarvis.learning.optimize.store import OptimizationStore
from openjarvis.learning.optimize.trial_runner import TrialRunner
from openjarvis.learning.optimize.types import (
    ObjectiveSpec,
    OptimizationRun,
    SearchSpace,
    TrialResult,
)

LOGGER = logging.getLogger(__name__)

# Mapping from objective metric names to RunSummary stat attribute + ".mean"
_SUMMARY_STAT_MAP: Dict[str, str] = {
    "avg_power_watts": "avg_power_watts",
    "throughput_tok_per_sec": "throughput_stats",
    "mfu_pct": "mfu_stats",
    "mbu_pct": "mbu_stats",
    "ipw": "ipw_stats",
    "ipj": "ipj_stats",
    "energy_per_output_token": "energy_per_output_token_stats",
    "throughput_per_watt": "throughput_per_watt_stats",
    "ttft": "ttft_stats",
    "mean_itl_ms": "itl_stats",
}


def _get_objective_value(trial: TrialResult, obj: ObjectiveSpec) -> float:
    """Read the metric value from a TrialResult for a given objective."""
    # Direct attributes on TrialResult
    direct = {
        "accuracy",
        "mean_latency_seconds",
        "total_cost_usd",
        "total_energy_joules",
    }
    if obj.metric in direct:
        return getattr(trial, obj.metric, 0.0)

    # avg_power_watts is a direct attr on RunSummary
    if obj.metric == "avg_power_watts" and trial.summary:
        return trial.summary.avg_power_watts

    # Stats-based metrics from RunSummary
    stat_attr = _SUMMARY_STAT_MAP.get(obj.metric)
    if stat_attr and trial.summary:
        stats = getattr(trial.summary, stat_attr, None)
        if stats is not None and hasattr(stats, "mean"):
            return stats.mean

    return 0.0


def compute_pareto_frontier(
    trials: List[TrialResult],
    objectives: List[ObjectiveSpec],
) -> List[TrialResult]:
    """Compute the Pareto frontier: trials not dominated by any other.

    A trial A dominates trial B if A is >= B on all objectives and > B
    on at least one (direction-aware: maximize flips the comparison).
    """
    if not trials or not objectives:
        return list(trials)

    def _values(trial: TrialResult) -> List[float]:
        vals = []
        for obj in objectives:
            v = _get_objective_value(trial, obj)
            # Normalize: for "minimize", negate so higher is always better
            if obj.direction == "minimize":
                v = -v
            vals.append(v)
        return vals

    trial_vals = [_values(t) for t in trials]
    frontier: List[TrialResult] = []

    for i, trial in enumerate(trials):
        dominated = False
        for j, other in enumerate(trials):
            if i == j:
                continue
            # Check if other dominates trial
            all_ge = all(
                trial_vals[j][k] >= trial_vals[i][k] for k in range(len(objectives))
            )
            any_gt = any(
                trial_vals[j][k] > trial_vals[i][k] for k in range(len(objectives))
            )
            if all_ge and any_gt:
                dominated = True
                break
        if not dominated:
            frontier.append(trial)

    return frontier


class OptimizationEngine:
    """Orchestrates the optimize loop: propose -> evaluate -> analyze -> repeat."""

    def __init__(
        self,
        search_space: SearchSpace,
        llm_optimizer: LLMOptimizer,
        trial_runner: TrialRunner,
        store: Optional[OptimizationStore] = None,
        max_trials: int = 20,
        early_stop_patience: int = 5,
    ) -> None:
        self.search_space = search_space
        self.llm_optimizer = llm_optimizer
        self.trial_runner = trial_runner
        self.store = store
        self.max_trials = max_trials
        self.early_stop_patience = early_stop_patience

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> OptimizationRun:
        """Execute the full optimization loop.

        1. Generate a run_id via uuid.
        2. ``llm_optimizer.propose_initial()`` -> first config.
        3. Loop up to ``max_trials``:
           a. ``trial_runner.run_trial(config)`` -> TrialResult
           b. ``llm_optimizer.analyze_trial(config, summary, traces)``
           c. Update TrialResult with analysis text
           d. Append to history
           e. If store, ``store.save_trial(result)``
           f. Update best_trial if accuracy improved
           g. Check early stopping (no improvement for *patience* trials)
           h. If not stopped, ``llm_optimizer.propose_next(history)``
        4. Set run status to ``"completed"``.
        5. If store, ``store.save_run(optimization_run)``.
        6. Return the :class:`OptimizationRun`.

        Args:
            progress_callback: Optional ``(trial_num, max_trials) -> None``
                called after each trial completes.
        """
        run_id = uuid.uuid4().hex[:16]
        # Detect benchmark name(s) from the trial runner
        from openjarvis.learning.optimize.trial_runner import MultiBenchTrialRunner

        benchmark_name = getattr(self.trial_runner, "benchmark", "")
        benchmark_names: List[str] = []
        if isinstance(self.trial_runner, MultiBenchTrialRunner):
            benchmark_names = [s.benchmark for s in self.trial_runner.benchmark_specs]
            benchmark_name = "+".join(benchmark_names)

        optimization_run = OptimizationRun(
            run_id=run_id,
            search_space=self.search_space,
            status="running",
            optimizer_model=self.llm_optimizer.optimizer_model,
            benchmark=benchmark_name,
            benchmarks=benchmark_names,
        )

        history: List[TrialResult] = []
        best_accuracy = -1.0
        trials_without_improvement = 0

        # First config
        config = self.llm_optimizer.propose_initial()

        for trial_num in range(1, self.max_trials + 1):
            LOGGER.info(
                "Trial %d/%d (id=%s)",
                trial_num,
                self.max_trials,
                config.trial_id,
            )

            # Evaluate
            result = self.trial_runner.run_trial(config)

            # Analyze — returns TrialFeedback
            if result.summary is not None:
                feedback = self.llm_optimizer.analyze_trial(
                    config,
                    result.summary,
                    sample_scores=result.sample_scores or None,
                    per_benchmark=result.per_benchmark or None,
                )
                result.structured_feedback = feedback
                result.analysis = feedback.summary_text
            elif result.per_benchmark:
                # Multi-benchmark composite: build a synthetic summary
                # for analysis from per_benchmark data
                from openjarvis.evals.core.types import RunSummary as _RS

                synth = _RS(
                    benchmark="multi",
                    category="multi",
                    backend="jarvis-agent",
                    model=result.config.params.get("intelligence.model", ""),
                    accuracy=result.accuracy,
                    mean_latency_seconds=result.mean_latency_seconds,
                    total_cost_usd=result.total_cost_usd,
                    total_energy_joules=result.total_energy_joules,
                    total_samples=result.samples_evaluated,
                    scored_samples=result.samples_evaluated,
                    correct=int(result.accuracy * result.samples_evaluated),
                    errors=0,
                    total_input_tokens=0,
                    total_output_tokens=result.total_tokens,
                )
                feedback = self.llm_optimizer.analyze_trial(
                    config,
                    synth,
                    per_benchmark=result.per_benchmark,
                )
                result.structured_feedback = feedback
                result.analysis = feedback.summary_text
            else:
                result.analysis = ""

            # Record
            history.append(result)
            optimization_run.trials.append(result)

            # Recompute Pareto frontier
            optimization_run.pareto_frontier = compute_pareto_frontier(
                history,
                optimization_run.objectives,
            )
            frontier_ids = {t.trial_id for t in optimization_run.pareto_frontier}

            # Persist trial
            if self.store is not None:
                self.store.save_trial(run_id, result)

            # Track best
            if result.accuracy > best_accuracy:
                best_accuracy = result.accuracy
                optimization_run.best_trial = result
                trials_without_improvement = 0
            else:
                trials_without_improvement += 1

            # Progress callback
            if progress_callback is not None:
                progress_callback(trial_num, self.max_trials)

            # Early stopping
            if trials_without_improvement >= self.early_stop_patience:
                LOGGER.info(
                    "Early stopping after %d trials without improvement.",
                    self.early_stop_patience,
                )
                break

            # Propose next (unless this was the last trial)
            if trial_num < self.max_trials:
                # Decide proposal strategy
                target_primitive = ""
                if result.structured_feedback:
                    target_primitive = result.structured_feedback.target_primitive

                if trial_num % 5 == 0 and len(optimization_run.pareto_frontier) >= 2:
                    # Merge frontier members periodically
                    candidates = optimization_run.pareto_frontier[:3]
                    config = self.llm_optimizer.propose_merge(
                        candidates,
                        history,
                        frontier_ids=frontier_ids,
                    )
                elif target_primitive and trial_num > 2:
                    # Targeted mutation on the suggested primitive
                    config = self.llm_optimizer.propose_targeted(
                        history,
                        result.config,
                        target_primitive,
                        frontier_ids=frontier_ids,
                    )
                else:
                    config = self.llm_optimizer.propose_next(
                        history,
                        frontier_ids=frontier_ids,
                    )

        optimization_run.status = "completed"

        if self.store is not None:
            self.store.save_run(optimization_run)

        return optimization_run

    def export_best_recipe(self, run: OptimizationRun, path: Path) -> Path:
        """Export the best trial's config as a TOML recipe file.

        Args:
            run: A completed :class:`OptimizationRun`.
            path: Destination path for the TOML file.

        Returns:
            The *path* written to.

        Raises:
            ValueError: If there is no best trial in the run.
        """
        if run.best_trial is None:
            raise ValueError("No best trial to export.")

        recipe_data = self._trial_to_recipe_dict(run.best_trial)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if tomli_w is not None:
            with open(path, "wb") as fh:
                tomli_w.dump(recipe_data, fh)
        else:
            # Fallback: write TOML manually
            self._write_toml_fallback(recipe_data, path)

        run.best_recipe_path = str(path)
        return path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _trial_to_recipe_dict(trial: TrialResult) -> Dict[str, Any]:
        """Convert a TrialResult into a Recipe-style TOML dict."""
        params = trial.config.params
        recipe: Dict[str, Any] = {
            "recipe": {
                "name": f"optimized-{trial.trial_id}",
                "description": (
                    f"Auto-optimized config (accuracy={trial.accuracy:.4f})"
                ),
                "version": "0.1.0",
            },
        }

        # Intelligence section
        intel: Dict[str, Any] = {}
        if "intelligence.model" in params:
            intel["model"] = params["intelligence.model"]
        if "intelligence.temperature" in params:
            intel["temperature"] = params["intelligence.temperature"]
        if "intelligence.quantization" in params:
            intel["quantization"] = params["intelligence.quantization"]
        if "intelligence.system_prompt" in params:
            intel["system_prompt"] = params["intelligence.system_prompt"]
        if "intelligence.max_tokens" in params:
            intel["max_tokens"] = params["intelligence.max_tokens"]
        if "intelligence.top_p" in params:
            intel["top_p"] = params["intelligence.top_p"]
        if intel:
            recipe["intelligence"] = intel

        # Engine section
        engine: Dict[str, Any] = {}
        if "engine.backend" in params:
            engine["key"] = params["engine.backend"]
        if engine:
            recipe["engine"] = engine

        # Agent section
        agent: Dict[str, Any] = {}
        if "agent.type" in params:
            agent["type"] = params["agent.type"]
        if "agent.max_turns" in params:
            agent["max_turns"] = params["agent.max_turns"]
        if "agent.system_prompt" in params:
            agent["system_prompt"] = params["agent.system_prompt"]
        if "tools.tool_set" in params:
            agent["tools"] = params["tools.tool_set"]
        if agent:
            recipe["agent"] = agent

        # Learning section
        learning: Dict[str, Any] = {}
        if "learning.routing_policy" in params:
            learning["routing"] = params["learning.routing_policy"]
        if "learning.agent_policy" in params:
            learning["agent"] = params["learning.agent_policy"]
        if learning:
            recipe["learning"] = learning

        return recipe

    @staticmethod
    def _write_toml_fallback(data: Dict[str, Any], path: Path) -> None:
        """Write a simple nested dict as TOML without tomli_w."""
        lines: List[str] = []
        for section, values in data.items():
            if not isinstance(values, dict):
                continue
            lines.append(f"[{section}]")
            for key, val in values.items():
                if isinstance(val, str):
                    lines.append(f'{key} = "{val}"')
                elif isinstance(val, bool):
                    lines.append(f"{key} = {'true' if val else 'false'}")
                elif isinstance(val, (int, float)):
                    lines.append(f"{key} = {val}")
                elif isinstance(val, list):
                    items = ", ".join(
                        f'"{v}"' if isinstance(v, str) else str(v) for v in val
                    )
                    lines.append(f"{key} = [{items}]")
                else:
                    lines.append(f'{key} = "{val}"')
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")


__all__ = ["OptimizationEngine", "compute_pareto_frontier"]
