"""SkillBenchmarkRunner — orchestrate the 4-condition × N-seed × M-task
PinchBench sweep that measures whether skills + DSPy/GEPA optimization
improves agent performance.

Plan 2B implementation.  See:
docs/superpowers/specs/2026-04-08-skills-benchmark-evaluation-design.md
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

CONDITIONS = (
    "no_skills",
    "skills_on",
    "skills_optimized_dspy",
    "skills_optimized_gepa",
)


# ---------------------------------------------------------------------------
# Config + result types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SkillBenchmarkConfig:
    """Configuration for a single SkillBenchmarkRunner sweep."""

    benchmark: str = "pinchbench"
    model: str = "qwen3.5:9b"
    engine: str = "ollama"
    agent: str = "native_react"
    tools: List[str] = field(
        default_factory=lambda: [
            "calculator",
            "think",
            "shell_exec",
            "web_search",
            "file_read",
            "file_write",
        ]
    )
    seeds: List[int] = field(default_factory=lambda: [42, 43, 44])
    max_samples: Optional[int] = None
    output_dir: Path = field(default_factory=lambda: Path("docs/superpowers/results/"))
    skills_dir: Path = field(
        default_factory=lambda: Path("~/.openjarvis/skills/").expanduser()
    )
    overlay_dir_dspy: Path = field(
        default_factory=lambda: Path("~/.openjarvis/learning/skills-dspy/").expanduser()
    )
    overlay_dir_gepa: Path = field(
        default_factory=lambda: Path("~/.openjarvis/learning/skills-gepa/").expanduser()
    )


@dataclass(slots=True)
class ConditionResult:
    """Aggregated result for a single condition across all seeds."""

    condition: str
    seeds: List[int]
    per_seed_pass_rate: Dict[int, float]
    mean_pass_rate: float
    stddev_pass_rate: float
    per_task_results: Dict[str, List[bool]]  # task_id → [pass_seed1, ...]
    skill_invocation_counts: Dict[str, int]  # skill_name → total invocations
    total_tokens: int
    total_runtime_seconds: float


@dataclass(slots=True)
class ConditionComparison:
    """Top-level result of a SkillBenchmarkRunner sweep."""

    config: SkillBenchmarkConfig
    started_at: str
    ended_at: str
    results: Dict[str, ConditionResult]
    deltas: Dict[str, float]


class SkillBenchmarkRunner:
    """Orchestrates the 4-condition × N-seed × M-task PinchBench sweep.

    Each condition is a different SystemBuilder configuration:
    - no_skills:               cfg.skills.enabled = False
    - skills_on:               enabled, overlay_dir = empty (no overlays load)
    - skills_optimized_dspy:   enabled, overlay_dir = config.overlay_dir_dspy
    - skills_optimized_gepa:   enabled, overlay_dir = config.overlay_dir_gepa

    Per-seed runs share the same backend instantiation but pass a fresh
    seed to the EvalRunner.
    """

    def __init__(self, config: SkillBenchmarkConfig) -> None:
        self._config = config
        # An "empty" overlay dir for the skills_on condition.  We point at
        # a known-empty subdirectory under the output dir so SkillManager
        # finds zero overlays even if the user happens to have populated
        # the default ~/.openjarvis/learning/skills/ tree.
        self._empty_overlay_dir = (
            Path(self._config.output_dir).expanduser() / "_skills_on_empty_overlays"
        )
        self._empty_overlay_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Per-condition backend construction
    # ------------------------------------------------------------------

    def _backend_kwargs_for_condition(self, condition: str) -> Dict[str, Any]:
        """Return the kwargs to pass to JarvisAgentBackend for *condition*.

        Pure function — no side effects, no SystemBuilder construction.
        Tested in isolation so we can verify the per-condition switches
        without invoking the engine.
        """
        if condition == "no_skills":
            return {
                "skills_enabled": False,
                "overlay_dir": None,
            }
        if condition == "skills_on":
            return {
                "skills_enabled": True,
                "overlay_dir": self._empty_overlay_dir,
            }
        if condition == "skills_optimized_dspy":
            return {
                "skills_enabled": True,
                "overlay_dir": self._config.overlay_dir_dspy,
            }
        if condition == "skills_optimized_gepa":
            return {
                "skills_enabled": True,
                "overlay_dir": self._config.overlay_dir_gepa,
            }
        raise ValueError(
            f"Unknown condition '{condition}'.  Expected one of: "
            f"{', '.join(CONDITIONS)}"
        )

    def _build_backend_for_condition(self, condition: str) -> Any:
        """Construct a JarvisAgentBackend for *condition*.

        Separate from `_backend_kwargs_for_condition` so the kwarg logic
        can be tested without instantiating an engine.
        """
        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        kw = self._backend_kwargs_for_condition(condition)
        return JarvisAgentBackend(
            engine_key=self._config.engine,
            agent_name=self._config.agent,
            tools=list(self._config.tools),
            telemetry=False,
            model=self._config.model,
            skills_enabled=kw["skills_enabled"],
            overlay_dir=kw["overlay_dir"],
        )

    # ------------------------------------------------------------------
    # Per-seed and per-condition runs
    # ------------------------------------------------------------------

    def _run_single_seed(
        self,
        condition: str,
        seed: int,
    ) -> Dict[str, Any]:
        """Run the benchmark once for one (condition, seed) pair.

        Returns a raw dict with per-task results, pass rate, skill
        invocation counts, total tokens, and total runtime.

        This method is the integration boundary with the existing
        EvalRunner / PinchBenchDataset.  It is intentionally a thin
        shim so tests can monkeypatch it without instantiating an
        engine or running real benchmark tasks.
        """
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend
        from openjarvis.evals.core.runner import EvalRunner
        from openjarvis.evals.core.types import RunConfig
        from openjarvis.evals.datasets.pinchbench import PinchBenchDataset
        from openjarvis.evals.scorers.pinchbench import PinchBenchScorer

        backend = self._build_backend_for_condition(condition)

        dataset = PinchBenchDataset(path=None)
        dataset.load(
            max_samples=self._config.max_samples,
            split=None,
            seed=seed,
        )

        # PinchBenchScorer is an LLM-as-judge scorer; it needs a judge
        # backend.  We reuse the same engine the agent uses (typically
        # a local Ollama model) so the headline run is fully local.
        try:
            judge_backend = JarvisDirectBackend(
                engine_key=self._config.engine,
            )
        except RuntimeError as exc:
            LOGGER.warning(
                "Judge backend unavailable, automated checks only: %s",
                exc,
            )
            judge_backend = None
        scorer = PinchBenchScorer(judge_backend, self._config.model)

        runner_cfg = RunConfig(
            benchmark=self._config.benchmark,
            backend="jarvis-agent",
            model=self._config.model,
            max_workers=1,
            episode_mode=False,
            seed=seed,
        )

        eval_runner = EvalRunner(
            config=runner_cfg,
            dataset=dataset,
            backend=backend,
            scorer=scorer,
        )

        t0 = time.monotonic()
        summary = eval_runner.run()
        elapsed = time.monotonic() - t0

        # Aggregate per-task results.  RunSummary doesn't carry the
        # per-record list — that lives on the runner instance via the
        # `results` property (which returns List[EvalResult]).
        per_task: Dict[str, bool] = {}
        for r in eval_runner.results:
            rid = getattr(r, "record_id", "") or ""
            ok = bool(getattr(r, "is_correct", False))
            if rid:
                per_task[rid] = ok

        # Pass rate.  Prefer the runner-computed accuracy when we have
        # records; fall back to summary.accuracy otherwise.
        if per_task:
            pass_rate = sum(1 for v in per_task.values() if v) / len(per_task)
        else:
            pass_rate = float(getattr(summary, "accuracy", 0.0) or 0.0)

        # Skill invocation counts from the trace store (if any)
        skill_invocations = self._extract_skill_invocations(backend)

        # Token totals.  RunSummary tracks input/output tokens separately.
        total_input = int(getattr(summary, "total_input_tokens", 0) or 0)
        total_output = int(getattr(summary, "total_output_tokens", 0) or 0)
        total_tokens = total_input + total_output

        return {
            "pass_rate": pass_rate,
            "per_task": per_task,
            "skill_invocations": skill_invocations,
            "total_tokens": total_tokens,
            "total_runtime_seconds": elapsed,
        }

    def _extract_skill_invocations(self, backend: Any) -> Dict[str, int]:
        """Count per-skill invocations in the trace store from this run.

        Walks all traces in the backend's system trace store and counts
        TraceStep.metadata.skill values.  Returns an empty dict on any
        failure (the count is informational, not load-bearing).
        """
        try:
            system = getattr(backend, "_system", None)
            if system is None:
                return {}
            store = getattr(system, "trace_store", None)
            if store is None:
                return {}
            traces = store.list_traces(limit=10000)
        except Exception:
            return {}

        counts: Dict[str, int] = {}
        for trace in traces:
            steps = getattr(trace, "steps", None) or []
            for step in steps:
                meta = getattr(step, "metadata", None) or {}
                if isinstance(meta, dict):
                    name = meta.get("skill")
                    if name:
                        counts[name] = counts.get(name, 0) + 1
        return counts

    def run_condition(self, condition: str) -> ConditionResult:
        """Run the benchmark for *condition* across all configured seeds.

        Returns a ConditionResult with mean ± stddev pass rate and the
        per-task / per-skill aggregations.
        """
        if condition not in CONDITIONS:
            raise ValueError(
                f"Unknown condition '{condition}'.  Expected one of: "
                f"{', '.join(CONDITIONS)}"
            )

        per_seed_pass_rate: Dict[int, float] = {}
        per_task_results: Dict[str, List[bool]] = {}
        skill_counts: Dict[str, int] = {}
        total_tokens = 0
        total_runtime = 0.0

        for seed in self._config.seeds:
            seed_data = self._run_single_seed(condition, seed)
            per_seed_pass_rate[seed] = float(seed_data["pass_rate"])

            for task_id, ok in seed_data["per_task"].items():
                per_task_results.setdefault(task_id, []).append(bool(ok))

            for skill_name, count in seed_data["skill_invocations"].items():
                skill_counts[skill_name] = skill_counts.get(skill_name, 0) + int(count)

            total_tokens += int(seed_data["total_tokens"])
            total_runtime += float(seed_data["total_runtime_seconds"])

        rates = list(per_seed_pass_rate.values())
        mean_rate = statistics.fmean(rates) if rates else 0.0
        stddev_rate = statistics.stdev(rates) if len(rates) > 1 else 0.0

        return ConditionResult(
            condition=condition,
            seeds=list(self._config.seeds),
            per_seed_pass_rate=per_seed_pass_rate,
            mean_pass_rate=mean_rate,
            stddev_pass_rate=stddev_rate,
            per_task_results=per_task_results,
            skill_invocation_counts=skill_counts,
            total_tokens=total_tokens,
            total_runtime_seconds=total_runtime,
        )

    # ------------------------------------------------------------------
    # Sweep + report
    # ------------------------------------------------------------------

    def run_all_conditions(self) -> ConditionComparison:
        """Run all 4 conditions × all seeds.

        Returns a ConditionComparison with per-condition results and the
        computed deltas (skills_on - no_skills, etc.).
        """
        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        results: Dict[str, ConditionResult] = {}
        for condition in CONDITIONS:
            LOGGER.info("Running condition: %s", condition)
            results[condition] = self.run_condition(condition)

        ended_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Compute the headline deltas
        deltas: Dict[str, float] = {}
        if "no_skills" in results and "skills_on" in results:
            deltas["skills_on - no_skills"] = (
                results["skills_on"].mean_pass_rate
                - results["no_skills"].mean_pass_rate
            )
        if "skills_on" in results and "skills_optimized_dspy" in results:
            deltas["skills_optimized_dspy - skills_on"] = (
                results["skills_optimized_dspy"].mean_pass_rate
                - results["skills_on"].mean_pass_rate
            )
        if "skills_on" in results and "skills_optimized_gepa" in results:
            deltas["skills_optimized_gepa - skills_on"] = (
                results["skills_optimized_gepa"].mean_pass_rate
                - results["skills_on"].mean_pass_rate
            )

        return ConditionComparison(
            config=self._config,
            started_at=started_at,
            ended_at=ended_at,
            results=results,
            deltas=deltas,
        )

    def write_report(self, comparison: ConditionComparison) -> Path:
        """Write a markdown report to output_dir.

        Filename: pinchbench-skills-eval-{YYYY-MM-DD}.md
        """
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_dir = Path(self._config.output_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"pinchbench-skills-eval-{date_str}.md"

        lines: List[str] = []
        lines.append(f"# PinchBench Skills Evaluation — {date_str}")
        lines.append("")
        lines.append(f"**Started:** {comparison.started_at}")
        lines.append(f"**Ended:** {comparison.ended_at}")
        lines.append(f"**Model:** {comparison.config.model}")
        lines.append(f"**Engine:** {comparison.config.engine}")
        lines.append(f"**Agent:** {comparison.config.agent}")
        lines.append(f"**Seeds:** {', '.join(str(s) for s in comparison.config.seeds)}")
        max_samples = comparison.config.max_samples
        lines.append(
            f"**Max samples:** {max_samples if max_samples is not None else 'full'}"
        )
        lines.append("")

        # Summary table
        lines.append("## Summary")
        lines.append("")
        lines.append(
            "| Condition | Mean pass rate | Stddev | Total tokens | Runtime (s) |"
        )
        lines.append("|---|---|---|---|---|")
        for condition in CONDITIONS:
            r = comparison.results.get(condition)
            if r is None:
                continue
            lines.append(
                f"| {condition} | {r.mean_pass_rate:.3f} | "
                f"{r.stddev_pass_rate:.3f} | {r.total_tokens} | "
                f"{r.total_runtime_seconds:.1f} |"
            )
        lines.append("")

        # Deltas
        if comparison.deltas:
            lines.append("## Deltas")
            lines.append("")
            for name, value in comparison.deltas.items():
                sign = "+" if value >= 0 else ""
                lines.append(f"- **{name}**: {sign}{value:.3f}")
            lines.append("")

        # Per-task breakdown
        lines.append("## Per-task results")
        lines.append("")
        all_tasks: set[str] = set()
        for r in comparison.results.values():
            all_tasks.update(r.per_task_results.keys())
        if all_tasks:
            header = "| Task | " + " | ".join(CONDITIONS) + " |"
            sep = "|---|" + "|".join(["---"] * len(CONDITIONS)) + "|"
            lines.append(header)
            lines.append(sep)
            for task_id in sorted(all_tasks):
                row = [task_id]
                for condition in CONDITIONS:
                    r = comparison.results.get(condition)
                    passes = (
                        r.per_task_results.get(task_id, []) if r is not None else []
                    )
                    if not passes:
                        row.append("—")
                    else:
                        n_pass = sum(1 for v in passes if v)
                        row.append(f"{n_pass}/{len(passes)}")
                lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        # Per-skill invocation counts
        lines.append("## Per-skill invocation counts")
        lines.append("")
        all_skills: set[str] = set()
        for r in comparison.results.values():
            all_skills.update(r.skill_invocation_counts.keys())
        if all_skills:
            header = "| Skill | " + " | ".join(CONDITIONS) + " |"
            sep = "|---|" + "|".join(["---"] * len(CONDITIONS)) + "|"
            lines.append(header)
            lines.append(sep)
            for skill_name in sorted(all_skills):
                row = [skill_name]
                for condition in CONDITIONS:
                    r = comparison.results.get(condition)
                    count = (
                        r.skill_invocation_counts.get(skill_name, 0)
                        if r is not None
                        else 0
                    )
                    row.append(str(count))
                lines.append("| " + " | ".join(row) + " |")
        else:
            lines.append("(no skill invocations recorded)")
        lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path


__all__ = [
    "CONDITIONS",
    "ConditionComparison",
    "ConditionResult",
    "SkillBenchmarkConfig",
    "SkillBenchmarkRunner",
]
