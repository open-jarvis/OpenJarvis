"""W&B experiment tracker for the eval framework."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from openjarvis.evals.core.tracker import ResultTracker
from openjarvis.evals.core.types import EvalResult, MetricStats, RunConfig, RunSummary

try:
    import wandb
except ImportError:
    wandb = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)


def _flatten_metric_stats(prefix: str, ms: Optional[MetricStats]) -> Dict[str, float]:
    """Flatten a MetricStats into a dict with prefixed keys."""
    if ms is None:
        return {}
    return {
        f"{prefix}_mean": ms.mean,
        f"{prefix}_median": ms.median,
        f"{prefix}_min": ms.min,
        f"{prefix}_max": ms.max,
        f"{prefix}_std": ms.std,
        f"{prefix}_p90": ms.p90,
        f"{prefix}_p95": ms.p95,
        f"{prefix}_p99": ms.p99,
    }


class WandbTracker(ResultTracker):
    """Streams per-sample metrics to Weights & Biases."""

    def __init__(
        self,
        project: str,
        entity: str = "",
        tags: str = "",
        group: str = "",
    ) -> None:
        if wandb is None:
            raise ImportError(
                "wandb is not installed. Install it with: uv sync --extra eval-wandb"
            )
        self._project = project
        self._entity = entity or None
        self._tags: List[str] = (
            [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        )
        self._group = group or None
        self._run: Any = None
        self._step = 0

    def on_run_start(self, config: RunConfig) -> None:
        run_config = {
            "benchmark": config.benchmark,
            "model": config.model,
            "backend": config.backend,
            "max_samples": config.max_samples,
            "max_workers": config.max_workers,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "seed": config.seed,
        }
        if config.agent_name:
            run_config["agent_name"] = config.agent_name
        if config.tools:
            run_config["tools"] = ",".join(config.tools)
        if config.engine_key:
            run_config["engine_key"] = config.engine_key

        self._run = wandb.init(
            project=self._project,
            entity=self._entity,
            tags=self._tags or None,
            group=self._group,
            config=run_config,
            reinit=True,
        )
        self._step = 0

    def on_result(self, result: EvalResult, config: RunConfig) -> None:
        if self._run is None:
            return
        self._step += 1
        log_data: Dict[str, Any] = {
            "sample/is_correct": 1.0 if result.is_correct else 0.0,
            "sample/latency_seconds": result.latency_seconds,
            "sample/prompt_tokens": result.prompt_tokens,
            "sample/completion_tokens": result.completion_tokens,
            "sample/cost_usd": result.cost_usd,
            "sample/ttft": result.ttft,
            "sample/energy_joules": result.energy_joules,
            "sample/power_watts": result.power_watts,
            "sample/throughput_tok_per_sec": result.throughput_tok_per_sec,
            "sample/ipw": result.ipw,
            "sample/ipj": result.ipj,
        }
        if result.error:
            log_data["sample/has_error"] = 1.0
        wandb.log(log_data, step=self._step)

    def on_summary(self, summary: RunSummary) -> None:
        if self._run is None:
            return
        flat: Dict[str, Any] = {
            "accuracy": summary.accuracy,
            "total_samples": summary.total_samples,
            "scored_samples": summary.scored_samples,
            "correct": summary.correct,
            "errors": summary.errors,
            "mean_latency_seconds": summary.mean_latency_seconds,
            "total_cost_usd": summary.total_cost_usd,
            "total_energy_joules": summary.total_energy_joules,
            "avg_power_watts": summary.avg_power_watts,
            "total_input_tokens": summary.total_input_tokens,
            "total_output_tokens": summary.total_output_tokens,
        }
        flat.update(_flatten_metric_stats("accuracy", summary.accuracy_stats))
        flat.update(_flatten_metric_stats("latency", summary.latency_stats))
        flat.update(_flatten_metric_stats("ttft", summary.ttft_stats))
        flat.update(_flatten_metric_stats("energy", summary.energy_stats))
        flat.update(_flatten_metric_stats("power", summary.power_stats))
        flat.update(
            _flatten_metric_stats("gpu_utilization", summary.gpu_utilization_stats)
        )
        flat.update(_flatten_metric_stats("throughput", summary.throughput_stats))
        flat.update(_flatten_metric_stats("mfu", summary.mfu_stats))
        flat.update(_flatten_metric_stats("mbu", summary.mbu_stats))
        flat.update(_flatten_metric_stats("ipw", summary.ipw_stats))
        flat.update(_flatten_metric_stats("ipj", summary.ipj_stats))
        flat.update(
            _flatten_metric_stats(
                "energy_per_output_token",
                summary.energy_per_output_token_stats,
            )
        )
        flat.update(
            _flatten_metric_stats(
                "throughput_per_watt",
                summary.throughput_per_watt_stats,
            )
        )
        flat.update(_flatten_metric_stats("itl", summary.itl_stats))
        wandb.run.summary.update(flat)

    def on_run_end(self) -> None:
        if self._run is not None:
            self._run.finish()
            self._run = None


__all__ = ["WandbTracker"]
