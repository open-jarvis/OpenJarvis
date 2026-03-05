"""Core data types for the optimization framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openjarvis.evals.core.types import RunSummary
from openjarvis.recipes.loader import Recipe


@dataclass(slots=True)
class SearchDimension:
    """One tunable dimension in the config space."""

    name: str  # e.g. "agent.type", "intelligence.temperature"
    dim_type: str  # "categorical", "continuous", "integer", "subset", "text"
    # categorical/subset: explicit options
    values: List[Any] = field(default_factory=list)
    low: Optional[float] = None  # continuous/integer lower bound
    high: Optional[float] = None  # continuous/integer upper bound
    description: str = ""  # human-readable explanation for the LLM optimizer
    pillar: str = ""  # intelligence | engine | agent | tools | learning


@dataclass(slots=True)
class SearchSpace:
    """The full space of configs the optimizer can propose."""

    dimensions: List[SearchDimension] = field(default_factory=list)
    fixed: Dict[str, Any] = field(default_factory=dict)  # params NOT being optimized
    constraints: List[str] = field(default_factory=list)  # natural language constraints

    def to_prompt_description(self) -> str:
        """Render search space as structured text for the LLM optimizer."""
        lines: List[str] = []
        lines.append("# Search Space")
        lines.append("")

        # Group dimensions by pillar
        by_pillar: Dict[str, List[SearchDimension]] = {}
        for dim in self.dimensions:
            key = dim.pillar or "other"
            by_pillar.setdefault(key, []).append(dim)

        for pillar, dims in sorted(by_pillar.items()):
            lines.append(f"## {pillar.title()}")
            for dim in dims:
                lines.append(f"- **{dim.name}** ({dim.dim_type})")
                if dim.description:
                    lines.append(f"  Description: {dim.description}")
                if dim.dim_type in ("categorical", "subset"):
                    lines.append(f"  Options: {dim.values}")
                elif dim.dim_type in ("continuous", "integer"):
                    lines.append(f"  Range: [{dim.low}, {dim.high}]")
                elif dim.dim_type == "text":
                    lines.append("  Free-form text")
            lines.append("")

        if self.fixed:
            lines.append("## Fixed Parameters")
            for k, v in sorted(self.fixed.items()):
                lines.append(f"- {k} = {v}")
            lines.append("")

        if self.constraints:
            lines.append("## Constraints")
            for c in self.constraints:
                lines.append(f"- {c}")
            lines.append("")

        return "\n".join(lines)


# Mapping from dotted param names to Recipe constructor fields.
_PARAM_TO_RECIPE: Dict[str, str] = {
    "intelligence.model": "model",
    "intelligence.temperature": "temperature",
    "intelligence.quantization": "quantization",
    "engine.backend": "engine_key",
    "agent.type": "agent_type",
    "agent.max_turns": "max_turns",
    "agent.system_prompt": "system_prompt",
    "tools.tool_set": "tools",
    "learning.routing_policy": "routing_policy",
    "learning.agent_policy": "agent_policy",
}


@dataclass(slots=True)
class SampleScore:
    """Per-sample metrics from an evaluation trial."""

    record_id: str
    is_correct: Optional[bool] = None
    score: Optional[float] = None
    latency_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
    ttft: float = 0.0
    energy_joules: float = 0.0
    power_watts: float = 0.0
    gpu_utilization_pct: float = 0.0
    throughput_tok_per_sec: float = 0.0
    mfu_pct: float = 0.0
    mbu_pct: float = 0.0
    ipw: float = 0.0
    ipj: float = 0.0
    energy_per_output_token_joules: float = 0.0
    throughput_per_watt: float = 0.0
    mean_itl_ms: float = 0.0


@dataclass(slots=True)
class TrialFeedback:
    """Structured feedback from trial analysis."""

    summary_text: str = ""
    failure_patterns: List[str] = field(default_factory=list)
    pillar_ratings: Dict[str, str] = field(default_factory=dict)
    suggested_changes: List[str] = field(default_factory=list)
    target_pillar: str = ""


@dataclass(slots=True)
class ObjectiveSpec:
    """A single optimization objective."""

    metric: str
    direction: str  # "maximize" or "minimize"
    weight: float = 1.0


DEFAULT_OBJECTIVES = [
    ObjectiveSpec("accuracy", "maximize"),
    ObjectiveSpec("mean_latency_seconds", "minimize"),
    ObjectiveSpec("total_cost_usd", "minimize"),
]

ALL_OBJECTIVES = [
    ObjectiveSpec("accuracy", "maximize"),
    ObjectiveSpec("mean_latency_seconds", "minimize"),
    ObjectiveSpec("total_cost_usd", "minimize"),
    ObjectiveSpec("total_energy_joules", "minimize"),
    ObjectiveSpec("avg_power_watts", "minimize"),
    ObjectiveSpec("throughput_tok_per_sec", "maximize"),
    ObjectiveSpec("mfu_pct", "maximize"),
    ObjectiveSpec("mbu_pct", "maximize"),
    ObjectiveSpec("ipw", "maximize"),
    ObjectiveSpec("ipj", "maximize"),
    ObjectiveSpec("energy_per_output_token", "minimize"),
    ObjectiveSpec("throughput_per_watt", "maximize"),
    ObjectiveSpec("ttft", "minimize"),
    ObjectiveSpec("mean_itl_ms", "minimize"),
]


@dataclass(slots=True)
class TrialConfig:
    """A single candidate configuration proposed by the optimizer."""

    trial_id: str
    params: Dict[str, Any] = field(default_factory=dict)  # dotted keys -> values
    reasoning: str = ""  # optimizer's explanation

    def to_recipe(self) -> Recipe:
        """Map params back to Recipe fields."""
        kwargs: Dict[str, Any] = {}
        for dotted_key, value in self.params.items():
            recipe_field = _PARAM_TO_RECIPE.get(dotted_key)
            if recipe_field is not None:
                kwargs[recipe_field] = value

        return Recipe(
            name=f"trial-{self.trial_id}",
            **kwargs,
        )


@dataclass(slots=True)
class TrialResult:
    """Result of evaluating a trial, with both scalar and textual feedback."""

    trial_id: str
    config: TrialConfig
    accuracy: float = 0.0
    mean_latency_seconds: float = 0.0
    total_cost_usd: float = 0.0
    total_energy_joules: float = 0.0
    total_tokens: int = 0
    samples_evaluated: int = 0
    analysis: str = ""
    failure_modes: List[str] = field(default_factory=list)
    per_sample_feedback: List[Dict[str, Any]] = field(default_factory=list)
    summary: Optional[RunSummary] = None
    sample_scores: List[SampleScore] = field(default_factory=list)
    structured_feedback: Optional[TrialFeedback] = None


@dataclass(slots=True)
class OptimizationRun:
    """Complete optimization session."""

    run_id: str
    search_space: SearchSpace
    trials: List[TrialResult] = field(default_factory=list)
    best_trial: Optional[TrialResult] = None
    best_recipe_path: Optional[str] = None
    status: str = "running"  # running | completed | failed
    optimizer_model: str = ""
    benchmark: str = ""
    pareto_frontier: List[TrialResult] = field(default_factory=list)
    objectives: List[ObjectiveSpec] = field(
        default_factory=lambda: list(DEFAULT_OBJECTIVES),
    )


__all__ = [
    "ALL_OBJECTIVES",
    "DEFAULT_OBJECTIVES",
    "ObjectiveSpec",
    "OptimizationRun",
    "SampleScore",
    "SearchDimension",
    "SearchSpace",
    "TrialConfig",
    "TrialFeedback",
    "TrialResult",
]
