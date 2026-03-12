"""TrainingDataMiner — extract supervised training pairs from the TraceStore.

Provides three extraction modes:

* **SFT pairs** — (input, output) pairs from high-quality traces for
  supervised fine-tuning.
* **Routing pairs** — per-query-class statistics identifying the best
  model for each class.
* **Agent config pairs** — per-query-class statistics identifying the
  best agent and tool combination.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from openjarvis.core.types import StepType, Trace
from openjarvis.learning.trace_policy import classify_query


class TrainingDataMiner:
    """Extract supervised training pairs from stored traces.

    Parameters
    ----------
    trace_store:
        Any object with a ``list_traces(limit=...)`` method returning
        ``List[Trace]`` (typically a :class:`TraceStore`).
    min_quality:
        Minimum ``feedback`` score for a trace to be included.
    min_samples_per_class:
        Minimum number of samples a query class must have to appear in
        routing/agent-config results.
    """

    def __init__(
        self,
        trace_store: Any,
        *,
        min_quality: float = 0.7,
        min_samples_per_class: int = 1,
    ) -> None:
        self._store = trace_store
        self._min_quality = min_quality
        self._min_samples_per_class = min_samples_per_class

    # -- helpers ----------------------------------------------------------------

    def _quality_traces(self, *, agent: str | None = None) -> List[Trace]:
        """Return traces whose feedback meets the quality threshold."""
        kwargs: Dict[str, Any] = {"limit": 10000}
        if agent is not None:
            kwargs["agent"] = agent
        all_traces = self._store.list_traces(**kwargs)
        return [
            t
            for t in all_traces
            if t.feedback is not None
            and t.feedback >= self._min_quality
            and t.outcome == "success"
        ]

    @staticmethod
    def _tools_from_trace(trace: Trace) -> List[str]:
        """Extract tool names from TOOL_CALL steps in a trace."""
        tools: List[str] = []
        for step in trace.steps:
            if step.step_type == StepType.TOOL_CALL:
                tool_name = step.input.get("tool")
                if tool_name:
                    tools.append(tool_name)
        return tools

    # -- public API -------------------------------------------------------------

    def extract_sft_pairs(self, *, agent: str | None = None) -> List[Dict[str, Any]]:
        """Return SFT training pairs from high-quality traces.

        Each entry is a dict with keys: ``input``, ``output``,
        ``query_class``, ``model``, ``feedback``.

        Duplicate ``(input, output)`` pairs are collapsed; the first
        occurrence is kept.
        """
        traces = self._quality_traces(agent=agent)
        seen: set[tuple[str, str]] = set()
        pairs: List[Dict[str, Any]] = []

        for t in traces:
            key = (t.query, t.result)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(
                {
                    "input": t.query,
                    "output": t.result,
                    "query_class": classify_query(t.query),
                    "model": t.model,
                    "feedback": t.feedback,
                }
            )

        return pairs

    def extract_routing_pairs(
        self, *, agent: str | None = None
    ) -> Dict[str, Dict[str, Any]]:
        """Return per-query-class routing recommendations.

        Returns a dict mapping query class to:

        * ``best_model`` — model with highest average feedback for the class.
        * ``avg_feedback`` — average feedback across all models for the class.
        * ``sample_count`` — total number of qualifying traces in the class.
        * ``all_models`` — dict of ``{model: {"avg_feedback": float, "count": int}}``.
        """
        traces = self._quality_traces(agent=agent)

        # Accumulate per (query_class, model) feedback scores
        class_model_scores: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for t in traces:
            qc = classify_query(t.query)
            class_model_scores[qc][t.model].append(t.feedback)  # type: ignore[arg-type]

        result: Dict[str, Dict[str, Any]] = {}
        for qc, model_scores in class_model_scores.items():
            total_count = sum(len(scores) for scores in model_scores.values())
            if total_count < self._min_samples_per_class:
                continue

            all_models: Dict[str, Dict[str, Any]] = {}
            best_model = ""
            best_avg = -1.0

            for model, scores in model_scores.items():
                avg = sum(scores) / len(scores)
                all_models[model] = {"avg_feedback": avg, "count": len(scores)}
                if avg > best_avg:
                    best_avg = avg
                    best_model = model

            total_scores = [s for scores in model_scores.values() for s in scores]
            overall_avg = sum(total_scores) / len(total_scores) if total_scores else 0.0

            result[qc] = {
                "best_model": best_model,
                "avg_feedback": overall_avg,
                "sample_count": total_count,
                "all_models": all_models,
            }

        return result

    def extract_agent_config_pairs(
        self, *, agent: str | None = None
    ) -> Dict[str, Dict[str, Any]]:
        """Return per-query-class agent and tool recommendations.

        Returns a dict mapping query class to:

        * ``best_agent`` — agent with the highest average feedback.
        * ``best_tools`` — most frequently used tools by the best agent.
        * ``avg_feedback`` — average feedback across all agents for the class.
        * ``sample_count`` — total number of qualifying traces in the class.
        """
        traces = self._quality_traces(agent=agent)

        # Accumulate per (query_class, agent) feedback and tools
        class_agent_scores: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        class_agent_tools: Dict[str, Dict[str, List[List[str]]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for t in traces:
            qc = classify_query(t.query)
            class_agent_scores[qc][t.agent].append(t.feedback)  # type: ignore[arg-type]
            tools = self._tools_from_trace(t)
            class_agent_tools[qc][t.agent].append(tools)

        result: Dict[str, Dict[str, Any]] = {}
        for qc, agent_scores in class_agent_scores.items():
            total_count = sum(len(scores) for scores in agent_scores.values())
            if total_count < self._min_samples_per_class:
                continue

            best_agent = ""
            best_avg = -1.0
            for agent, scores in agent_scores.items():
                avg = sum(scores) / len(scores)
                if avg > best_avg:
                    best_avg = avg
                    best_agent = agent

            # Collect tool frequency for best agent
            tool_freq: Dict[str, int] = defaultdict(int)
            for tool_list in class_agent_tools[qc].get(best_agent, []):
                for tool in tool_list:
                    tool_freq[tool] += 1

            best_tools = sorted(tool_freq, key=tool_freq.get, reverse=True)  # type: ignore[arg-type]

            total_scores = [s for scores in agent_scores.values() for s in scores]
            overall_avg = sum(total_scores) / len(total_scores) if total_scores else 0.0

            result[qc] = {
                "best_agent": best_agent,
                "best_tools": best_tools,
                "avg_feedback": overall_avg,
                "sample_count": total_count,
            }

        return result


__all__ = ["TrainingDataMiner"]
