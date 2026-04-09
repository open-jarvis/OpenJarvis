"""SkillOptimizer — per-skill DSPy/GEPA optimization wrapper (Plan 2A).

Buckets traces by skill name, runs the underlying optimizer on each skill's
bucket, and writes the result as a sidecar overlay file in
``~/.openjarvis/learning/skills/<skill-name>/optimized.toml``.

The actual DSPy/GEPA invocation is done in ``_run_dspy`` / ``_run_gepa``,
which are isolated for easy mocking in tests.  In Plan 2A these are
deliberately minimal — they call the existing optimizer modules and extract
the description + few-shot examples.  Plan 2B will measure the impact via
benchmarks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.types import Trace, TraceStep
from openjarvis.skills.manager import SkillManager
from openjarvis.skills.overlay import SkillOverlay, write_overlay

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SkillOptimizationResult:
    """Result of optimizing a single skill."""

    skill_name: str
    status: str  # "optimized" | "skipped" | "error"
    trace_count: int = 0
    overlay_path: Optional[Path] = None
    error: str = ""


@dataclass(slots=True)
class _OptimizerOutput:
    """Internal: extracted output from the underlying DSPy/GEPA optimizer."""

    description: str = ""
    few_shot: List[Dict[str, str]] = field(default_factory=list)


class SkillOptimizer:
    """Per-skill optimization wrapper around DSPyAgentOptimizer / GEPA.

    Parameters
    ----------
    min_traces_per_skill:
        Minimum trace count for a skill to be eligible for optimization.
    optimizer:
        ``"dspy"`` or ``"gepa"``.  Determines which underlying optimizer is
        called inside ``_run_dspy`` / ``_run_gepa``.
    """

    def __init__(
        self,
        *,
        min_traces_per_skill: int = 20,
        optimizer: str = "dspy",
    ) -> None:
        self._min_traces = min_traces_per_skill
        self._optimizer = optimizer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(
        self,
        trace_store: Any,
        skill_manager: SkillManager,
        *,
        overlay_dir: Optional[Path] = None,
    ) -> Dict[str, SkillOptimizationResult]:
        """Run the per-skill optimization loop.

        Returns a dict mapping skill name to result.  Writes overlay TOML
        files for each skill that produced output.
        """
        if overlay_dir is None:
            # Try config first; fall back to the default tree.
            try:
                from openjarvis.core.config import load_config

                cfg = load_config()
                cfg_dir = getattr(
                    getattr(cfg.learning, "skills", None),
                    "overlay_dir",
                    None,
                )
                if cfg_dir:
                    overlay_dir = Path(cfg_dir).expanduser()
            except Exception:
                pass
            if overlay_dir is None:
                overlay_dir = Path(
                    "~/.openjarvis/learning/skills/"
                ).expanduser()
        overlay_dir = Path(overlay_dir).expanduser()

        traces = trace_store.list_traces(limit=10000)
        buckets = self._bucket_traces_by_skill(traces)

        results: Dict[str, SkillOptimizationResult] = {}
        for skill_name, skill_traces in buckets.items():
            if len(skill_traces) < self._min_traces:
                results[skill_name] = SkillOptimizationResult(
                    skill_name=skill_name,
                    status="skipped",
                    trace_count=len(skill_traces),
                )
                continue

            try:
                if self._optimizer == "gepa":
                    output = self._run_gepa(skill_name, skill_traces)
                else:
                    output = self._run_dspy(skill_name, skill_traces)
            except Exception as exc:
                LOGGER.warning("Skill optimizer failed for '%s': %s", skill_name, exc)
                results[skill_name] = SkillOptimizationResult(
                    skill_name=skill_name,
                    status="error",
                    trace_count=len(skill_traces),
                    error=str(exc),
                )
                continue

            overlay = SkillOverlay(
                skill_name=skill_name,
                optimizer=self._optimizer,
                optimized_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                trace_count=len(skill_traces),
                description=output.description,
                few_shot=list(output.few_shot),
            )
            path = write_overlay(overlay, overlay_dir)
            results[skill_name] = SkillOptimizationResult(
                skill_name=skill_name,
                status="optimized",
                trace_count=len(skill_traces),
                overlay_path=path,
            )

        return results

    # ------------------------------------------------------------------
    # Bucketing
    # ------------------------------------------------------------------

    def _bucket_traces_by_skill(self, traces: List[Trace]) -> Dict[str, List[Trace]]:
        """Group traces by the skill names they invoked.

        A trace is added to a skill's bucket once for each unique skill it
        invoked.  Traces with no skill-tagged tool calls are dropped entirely.
        """
        buckets: Dict[str, List[Trace]] = {}
        for trace in traces:
            skill_names = self._extract_skill_names(trace)
            for name in skill_names:
                buckets.setdefault(name, []).append(trace)
        return buckets

    @staticmethod
    def _extract_skill_names(trace: Trace) -> List[str]:
        """Return the unique skill names invoked in *trace*'s tool steps."""
        seen: List[str] = []
        steps = getattr(trace, "steps", []) or []
        for step in steps:
            metadata: Dict[str, Any] = {}
            if isinstance(step, dict):
                metadata = step.get("metadata", {}) or {}
            elif isinstance(step, TraceStep):
                metadata = step.metadata or {}
            else:
                metadata = getattr(step, "metadata", {}) or {}
            skill_name = metadata.get("skill")
            if skill_name and skill_name not in seen:
                seen.append(skill_name)
        return seen

    # ------------------------------------------------------------------
    # Underlying optimizers (mockable in tests)
    # ------------------------------------------------------------------

    def _run_dspy(
        self,
        skill_name: str,
        skill_traces: List[Trace],
    ) -> _OptimizerOutput:
        """Run DSPyAgentOptimizer on the bucket and extract description + few-shot.

        In Plan 2A this is intentionally simple — it pulls the few highest-
        feedback traces as candidate few-shot examples and uses the agent
        optimizer's output `system_prompt` as the new skill description if
        non-empty.  Plan 2B will measure and refine.
        """
        from openjarvis.core.config import DSPyOptimizerConfig
        from openjarvis.learning.agents.dspy_optimizer import DSPyAgentOptimizer

        cfg = DSPyOptimizerConfig(
            min_traces=max(1, self._min_traces),
            max_bootstrapped_demos=4,
            max_labeled_demos=4,
        )
        optimizer = DSPyAgentOptimizer(cfg)

        # Build a tiny in-memory trace store shim for the underlying optimizer
        class _BucketStore:
            def __init__(self, _traces):
                self._traces = _traces

            def list_traces(self, *, limit=100, **_kwargs):
                return list(self._traces[:limit])

        try:
            updates = optimizer.optimize(_BucketStore(skill_traces)) or {}
        except Exception as exc:
            LOGGER.warning(
                "DSPyAgentOptimizer raised for '%s' (using empty output): %s",
                skill_name,
                exc,
            )
            updates = {}

        description = str(updates.get("system_prompt", "")) if updates else ""
        few_shot_raw = updates.get("few_shot_examples", []) if updates else []
        few_shot: List[Dict[str, str]] = []
        for item in few_shot_raw or []:
            if isinstance(item, dict):
                few_shot.append(
                    {
                        "input": str(item.get("input", "")),
                        "output": str(item.get("output", "")),
                    }
                )

        # Fallback: if DSPy produced nothing, derive few-shot from top traces
        if not few_shot:
            top = sorted(
                skill_traces,
                key=lambda t: t.feedback if t.feedback is not None else 0.0,
                reverse=True,
            )[:4]
            for tr in top:
                if tr.query and tr.result:
                    few_shot.append({"input": tr.query, "output": tr.result})

        return _OptimizerOutput(description=description, few_shot=few_shot)

    def _run_gepa(
        self,
        skill_name: str,
        skill_traces: List[Trace],
    ) -> _OptimizerOutput:
        """Run GEPAAgentOptimizer on the bucket.  Same shape as _run_dspy."""
        from openjarvis.core.config import GEPAOptimizerConfig
        from openjarvis.learning.agents.gepa_optimizer import GEPAAgentOptimizer

        cfg = GEPAOptimizerConfig(min_traces=max(1, self._min_traces))
        optimizer = GEPAAgentOptimizer(cfg)

        class _BucketStore:
            def __init__(self, _traces):
                self._traces = _traces

            def list_traces(self, *, limit=100, **_kwargs):
                return list(self._traces[:limit])

        try:
            updates = optimizer.optimize(_BucketStore(skill_traces)) or {}
        except Exception as exc:
            LOGGER.warning(
                "GEPAAgentOptimizer raised for '%s' (using empty output): %s",
                skill_name,
                exc,
            )
            updates = {}

        description = str(updates.get("system_prompt", "")) if updates else ""

        # Parse GEPA's few_shot_examples output (matches DSPy path semantics)
        few_shot_raw = updates.get("few_shot_examples", []) if updates else []
        few_shot: List[Dict[str, str]] = []
        for item in few_shot_raw or []:
            if isinstance(item, dict):
                few_shot.append(
                    {
                        "input": str(item.get("input", "")),
                        "output": str(item.get("output", "")),
                    }
                )

        # Fallback: if GEPA produced nothing, derive few-shot from top traces
        if not few_shot:
            top = sorted(
                skill_traces,
                key=lambda t: t.feedback if t.feedback is not None else 0.0,
                reverse=True,
            )[:4]
            for tr in top:
                if tr.query and tr.result:
                    few_shot.append({"input": tr.query, "output": tr.result})
        return _OptimizerOutput(description=description, few_shot=few_shot)


__all__ = ["SkillOptimizer", "SkillOptimizationResult"]
