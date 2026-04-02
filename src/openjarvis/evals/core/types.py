"""Core data types for the evaluation framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class EvalRecord:
    """A single evaluation sample."""

    record_id: str
    problem: str
    reference: str
    category: str  # "chat" | "reasoning" | "rag" | "agentic"
    subject: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvalResult:
    """Result of evaluating a single sample."""

    record_id: str
    model_answer: str
    is_correct: Optional[bool] = None
    score: Optional[float] = None
    latency_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
    scoring_metadata: Dict[str, Any] = field(default_factory=dict)
    ttft: float = 0.0
    energy_joules: float = 0.0
    power_watts: float = 0.0
    gpu_utilization_pct: float = 0.0
    throughput_tok_per_sec: float = 0.0
    mfu_pct: float = 0.0
    mbu_pct: float = 0.0
    ipw: float = 0.0  # Intelligence Per Watt
    ipj: float = 0.0  # Intelligence Per Joule
    energy_per_output_token_joules: float = 0.0
    throughput_per_watt: float = 0.0
    mean_itl_ms: float = 0.0
    estimated_flops: float = 0.0
    trace_steps: int = 0
    trace_energy_joules: float = 0.0
    trace_data: Optional[Dict[str, Any]] = None


@dataclass(slots=True)
class RunConfig:
    """Configuration for an evaluation run."""

    benchmark: str
    backend: str
    model: str
    max_samples: Optional[int] = None
    max_workers: int = 4
    temperature: float = 0.0
    max_tokens: int = 2048
    judge_model: str = "gpt-5-mini-2025-08-07"
    judge_engine: str = "cloud"
    engine_key: Optional[str] = None
    agent_name: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    output_path: Optional[str] = None
    seed: int = 42
    dataset_split: Optional[str] = None
    telemetry: bool = False
    gpu_metrics: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    warmup_samples: int = 0
    wandb_project: str = ""
    wandb_entity: str = ""
    wandb_tags: str = ""
    wandb_group: str = ""
    sheets_spreadsheet_id: str = ""
    sheets_worksheet: str = "Results"
    sheets_credentials_path: str = ""
    system_prompt: str = ""
    episode_mode: bool = False
    dataset_subset: Optional[str] = None


@dataclass(slots=True)
class MetricStats:
    """Descriptive statistics for a single metric across samples."""

    mean: float = 0.0
    median: float = 0.0
    min: float = 0.0
    max: float = 0.0
    std: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0


@dataclass(slots=True)
class RunSummary:
    """Summary statistics for a completed evaluation run."""

    benchmark: str
    category: str
    backend: str
    model: str
    total_samples: int
    scored_samples: int
    correct: int
    accuracy: float
    errors: int
    mean_latency_seconds: float
    total_cost_usd: float
    per_subject: Dict[str, Dict[str, float]] = field(default_factory=dict)
    started_at: float = 0.0
    ended_at: float = 0.0
    accuracy_stats: Optional[MetricStats] = None
    latency_stats: Optional[MetricStats] = None
    ttft_stats: Optional[MetricStats] = None
    energy_stats: Optional[MetricStats] = None
    power_stats: Optional[MetricStats] = None
    gpu_utilization_stats: Optional[MetricStats] = None
    throughput_stats: Optional[MetricStats] = None
    mfu_stats: Optional[MetricStats] = None
    mbu_stats: Optional[MetricStats] = None
    ipw_stats: Optional[MetricStats] = None
    ipj_stats: Optional[MetricStats] = None
    energy_per_output_token_stats: Optional[MetricStats] = None
    throughput_per_watt_stats: Optional[MetricStats] = None
    itl_stats: Optional[MetricStats] = None
    input_token_stats: Optional[MetricStats] = None
    output_token_stats: Optional[MetricStats] = None
    total_energy_joules: float = 0.0
    total_estimated_flops: float = 0.0
    flops_stats: Optional[MetricStats] = None
    warmup_samples_excluded: int = 0
    steady_state_reached: bool = False
    energy_method: str = ""
    avg_power_watts: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    trace_step_type_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    efficiency: Optional[Dict[str, Any]] = None
    normalized_statistics: Optional[Dict[str, Any]] = None
    normalized_efficiency: Optional[Dict[str, Any]] = None
    # Internal fields set by the runner after construction
    _output_path: Optional[Path] = None
    _traces_dir: Optional[Path] = None


# ---------------------------------------------------------------------------
# Eval suite config dataclasses (TOML config system)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MetaConfig:
    """Suite-level metadata."""

    name: str = ""
    description: str = ""


@dataclass(slots=True)
class DefaultsConfig:
    """Default generation parameters applied to all runs."""

    temperature: float = 0.0
    max_tokens: int = 2048


@dataclass(slots=True)
class JudgeConfig:
    """Configuration for the LLM judge."""

    model: str = "gpt-5-mini-2025-08-07"
    engine: Optional[str] = None
    provider: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 1024


@dataclass(slots=True)
class ExecutionConfig:
    """Execution-level settings for the eval run."""

    max_workers: int = 4
    output_dir: str = "results/"
    seed: int = 42
    telemetry: bool = False
    gpu_metrics: bool = False
    warmup_samples: int = 0
    energy_vendor: str = ""
    wandb_project: str = ""
    wandb_entity: str = ""
    wandb_tags: str = ""
    wandb_group: str = ""
    sheets_spreadsheet_id: str = ""
    sheets_worksheet: str = "Results"
    sheets_credentials_path: str = ""


@dataclass(slots=True)
class ModelConfig:
    """Configuration for a single model in the eval suite."""

    name: str = ""
    engine: Optional[str] = None
    provider: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    param_count_b: float = 0.0
    active_params_b: Optional[float] = None
    gpu_peak_tflops: float = 0.0
    gpu_peak_bandwidth_gb_s: float = 0.0
    num_gpus: int = 1


@dataclass(slots=True)
class BenchmarkConfig:
    """Configuration for a single benchmark in the eval suite."""

    name: str = ""
    backend: str = "jarvis-direct"
    max_samples: Optional[int] = None
    split: Optional[str] = None
    agent: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    judge_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    subset: Optional[str] = None


@dataclass(slots=True)
class EvalSuiteConfig:
    """Top-level configuration for an eval suite (models x benchmarks)."""

    meta: MetaConfig = field(default_factory=MetaConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    run: ExecutionConfig = field(default_factory=ExecutionConfig)
    models: List[ModelConfig] = field(default_factory=list)
    benchmarks: List[BenchmarkConfig] = field(default_factory=list)


__all__ = [
    "EvalRecord",
    "EvalResult",
    "MetricStats",
    "RunConfig",
    "RunSummary",
    "MetaConfig",
    "DefaultsConfig",
    "JudgeConfig",
    "ExecutionConfig",
    "ModelConfig",
    "BenchmarkConfig",
    "EvalSuiteConfig",
]
