"""GEPA agent optimizer -- Pareto-efficient evolutionary optimization.

Uses GEPA's adapter pattern to bridge OpenJarvis traces into GEPA's
evolutionary optimization framework. Outputs TOML config updates
written via AgentConfigEvolver.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from openjarvis.core.config import GEPAOptimizerConfig
from openjarvis.core.registry import LearningRegistry
from openjarvis.learning._stubs import AgentLearningPolicy

logger = logging.getLogger(__name__)

# Optional dependency
try:
    import gepa

    HAS_GEPA = True
except ImportError:
    HAS_GEPA = False
    gepa = None  # type: ignore[assignment]


class OpenJarvisGEPAAdapter:
    """Implements GEPA's adapter protocol for OpenJarvis agents.

    Bridges trace data into GEPA's optimization framework via
    the ``assess()`` and ``make_reflective_dataset()`` methods.
    """

    def __init__(
        self,
        trace_store: Any,
        agent_name: str,
        config: GEPAOptimizerConfig,
    ) -> None:
        self.trace_store = trace_store
        self.agent_name = agent_name
        self.config = config
        self._traces: List[Any] = []

    def load_traces(self) -> None:
        """Load traces from the store."""
        kwargs: Dict[str, Any] = {"limit": 10_000}
        if self.agent_name:
            kwargs["agent"] = self.agent_name
        self._traces = self.trace_store.list_traces(**kwargs)

    def assess(
        self,
        batch: List[Any],
        candidate: Dict[str, Any],
        capture_traces: bool = False,
    ) -> Dict[str, Any]:
        """Score a candidate config against a batch of test cases.

        Returns a dict with at least 'scores' (list of floats) key.
        """
        scores = []
        trace_data = []

        for item in batch:
            query = item if isinstance(item, str) else getattr(item, "query", str(item))
            # Find matching traces for this query
            matching = [t for t in self._traces if t.query == query]
            if matching:
                best = max(matching, key=lambda t: t.feedback or 0.0)
                scores.append(best.feedback or 0.0)
                if capture_traces:
                    trace_data.append(
                        {
                            "query": query,
                            "result": best.result,
                            "feedback": best.feedback,
                            "outcome": best.outcome,
                            "steps": [
                                {
                                    "type": str(s.step_type),
                                    "input": s.input,
                                    "output": s.output,
                                }
                                for s in best.steps
                            ],
                        }
                    )
            else:
                scores.append(0.0)

        result: Dict[str, Any] = {"scores": scores}
        if capture_traces:
            result["traces"] = trace_data
        return result

    def make_reflective_dataset(
        self,
        candidate: Dict[str, Any],
        assessment_batch: List[Any],
        components_to_update: List[str],
    ) -> List[Dict[str, Any]]:
        """Package trace diagnostics as Actionable Side Information for GEPA."""
        dataset = []
        for item in assessment_batch:
            query = item if isinstance(item, str) else getattr(item, "query", str(item))
            matching = [t for t in self._traces if t.query == query]
            if not matching:
                continue
            best = max(matching, key=lambda t: t.feedback or 0.0)

            # Build diagnostic info
            tool_calls = []
            reasoning_steps = []
            errors = []
            for step in best.steps:
                step_type = str(step.step_type)
                if "tool_call" in step_type:
                    tool_calls.append(step.input.get("tool", "unknown"))
                if "generate" in step_type:
                    reasoning_steps.append(str(step.output)[:200])
                is_error = (
                    step.output
                    and isinstance(step.output, dict)
                    and "error" in step.output
                )
                if is_error:
                    errors.append(step.output["error"])

            dataset.append(
                {
                    "query": query,
                    "result": best.result,
                    "feedback": best.feedback,
                    "outcome": best.outcome,
                    "tool_calls": tool_calls,
                    "reasoning_steps": reasoning_steps,
                    "errors": errors,
                    "components_to_update": components_to_update,
                }
            )

        return dataset


class GEPAAgentOptimizer:
    """Optimize agent configs using GEPA evolutionary optimization.

    Parameters
    ----------
    config:
        GEPAOptimizerConfig controlling optimization parameters.
    """

    def __init__(self, config: GEPAOptimizerConfig) -> None:
        self.config = config

    def optimize(self, trace_store: Any) -> Dict[str, Any]:
        """Run GEPA optimization on traces from the store.

        1. Load traces and build the GEPA adapter
        2. Define the search space (agent config fields)
        3. Run GEPA's evolutionary optimization
        4. Extract best candidate as TOML updates
        5. Write via AgentConfigEvolver if config_dir is set
        """
        kwargs: Dict[str, Any] = {"limit": 10_000}
        if self.config.agent_filter:
            kwargs["agent"] = self.config.agent_filter
        traces = trace_store.list_traces(**kwargs)

        if len(traces) < self.config.min_traces:
            return {
                "status": "skipped",
                "reason": (
                    f"only {len(traces)} traces, min_traces={self.config.min_traces}"
                ),
            }

        if not HAS_GEPA:
            return {
                "status": "error",
                "reason": (
                    "gepa not installed (pip install 'openjarvis[learning-gepa]')"
                ),
            }

        agent_name = self.config.agent_filter or "default"
        adapter = OpenJarvisGEPAAdapter(trace_store, agent_name, self.config)
        adapter.load_traces()

        try:
            best_candidate = self._run_gepa(adapter, traces)
        except Exception as exc:
            logger.warning("GEPA optimization failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

        config_updates = self._to_config_updates(best_candidate)

        if self.config.config_dir:
            self._write_configs(agent_name, config_updates)

        return {
            "status": "completed",
            "traces_used": len(traces),
            "config_updates": config_updates,
        }

    def _run_gepa(
        self,
        adapter: OpenJarvisGEPAAdapter,
        traces: List[Any],
    ) -> Dict[str, Any]:
        """Run the GEPA evolutionary optimization loop."""
        # Build search space from config flags
        components = []
        if self.config.optimize_system_prompt:
            components.append("system_prompt")
        if self.config.optimize_tools:
            components.append("tools")
        if self.config.optimize_max_turns:
            components.append("max_turns")
        if self.config.optimize_temperature:
            components.append("temperature")

        # Extract unique queries as test cases
        queries = list({t.query for t in traces})

        # Initialize GEPA optimizer
        optimizer = gepa.GEPAOptimizer(
            adapter=adapter,
            max_metric_calls=self.config.max_metric_calls,
            population_size=self.config.population_size,
        )

        # Define initial candidate from trace analysis
        initial_candidate = self._build_initial_candidate(traces)

        # Run optimization
        result = optimizer.optimize(
            initial_candidate=initial_candidate,
            test_cases=queries[: self.config.assessment_batch_size],
            components=components,
        )

        return result.best_candidate if hasattr(result, "best_candidate") else result

    def _build_initial_candidate(self, traces: List[Any]) -> Dict[str, Any]:
        """Build initial candidate config from trace analysis."""
        # Collect tool usage frequencies
        tool_freq: Dict[str, int] = {}
        turn_counts: List[int] = []

        for t in traces:
            n_tools = 0
            for step in t.steps:
                step_type = str(step.step_type)
                if "tool_call" in step_type:
                    n_tools += 1
                    tool_name = step.input.get("tool", "") if step.input else ""
                    if tool_name:
                        tool_freq[tool_name] = tool_freq.get(tool_name, 0) + 1
            turn_counts.append(n_tools)

        ranked_tools = sorted(tool_freq, key=tool_freq.get, reverse=True)  # type: ignore[arg-type]

        avg_turns = sum(turn_counts) / len(turn_counts) if turn_counts else 10
        max_turns = max(int(avg_turns * 1.5), 5)

        return {
            "system_prompt": "",
            "tools": ranked_tools[:10],
            "max_turns": max_turns,
            "temperature": 0.3,
        }

    def _to_config_updates(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Convert GEPA candidate to TOML-compatible config dict."""
        updates: Dict[str, Any] = {}
        if self.config.optimize_system_prompt and "system_prompt" in candidate:
            updates["system_prompt"] = candidate["system_prompt"]
        if self.config.optimize_tools and "tools" in candidate:
            updates["tools"] = candidate["tools"]
        if self.config.optimize_max_turns and "max_turns" in candidate:
            updates["max_turns"] = candidate["max_turns"]
        if self.config.optimize_temperature and "temperature" in candidate:
            updates["temperature"] = candidate["temperature"]
        return updates

    def _write_configs(self, agent_name: str, config_updates: Dict[str, Any]) -> None:
        """Write updated configs via AgentConfigEvolver."""
        import pathlib

        from openjarvis.learning.agents.agent_evolver import AgentConfigEvolver

        evolver = AgentConfigEvolver.__new__(AgentConfigEvolver)
        evolver._config_dir = pathlib.Path(self.config.config_dir)
        evolver._history_dir = evolver._config_dir / ".history"
        evolver._config_dir.mkdir(parents=True, exist_ok=True)
        evolver._history_dir.mkdir(parents=True, exist_ok=True)

        evolver.write_config(
            agent_name,
            tools=config_updates.get("tools", []),
            max_turns=config_updates.get("max_turns", 10),
            temperature=config_updates.get("temperature", 0.3),
            system_prompt=config_updates.get("system_prompt", ""),
        )


@LearningRegistry.register("gepa")
class _GEPALearningPolicy(AgentLearningPolicy):
    """Wrapper to register GEPAAgentOptimizer in the LearningRegistry."""

    def __init__(self, **kwargs: object) -> None:
        pass

    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        config = GEPAOptimizerConfig()
        optimizer = GEPAAgentOptimizer(config)
        return optimizer.optimize(trace_store)


__all__ = ["GEPAAgentOptimizer", "OpenJarvisGEPAAdapter"]
