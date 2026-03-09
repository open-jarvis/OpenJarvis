"""LM-guided agent restructuring — analyzes traces and suggests improvements."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from openjarvis.core.registry import LearningRegistry
from openjarvis.learning._stubs import AgentLearningPolicy

logger = logging.getLogger(__name__)


@LearningRegistry.register("agent_advisor")
class AgentAdvisorPolicy(AgentLearningPolicy):
    """Higher-level LM analyzes traces, suggests agent structure changes.

    Does NOT auto-apply changes — returns recommendations that can be
    reviewed or applied via config.
    """

    def __init__(
        self,
        *,
        advisor_engine: Any = None,
        advisor_model: str = "",
        max_traces: int = 50,
    ) -> None:
        self._advisor_engine = advisor_engine
        self._advisor_model = advisor_model
        self._max_traces = max_traces

    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        """Analyze traces and return agent improvement recommendations."""
        try:
            traces = trace_store.list_traces()
        except Exception as exc:
            logger.warning("Agent advisor analysis failed: %s", exc)
            return {"recommendations": [], "confidence": 0.0}

        # Collect failing or slow traces
        problem_traces = []
        for trace in traces[-self._max_traces :]:
            is_failing = trace.outcome != "success"
            is_slow = (trace.total_latency_seconds or 0) > 5.0
            if is_failing or is_slow:
                problem_traces.append(trace)

        if not problem_traces:
            return {
                "recommendations": [],
                "confidence": 1.0,
                "message": "No problematic traces found",
            }

        # Analyze patterns without LM (structural analysis)
        recommendations = self._analyze_patterns(problem_traces)

        # If advisor engine available, get LM-guided recommendations
        if self._advisor_engine and self._advisor_model:
            try:
                lm_recs = self._get_lm_recommendations(problem_traces)
                recommendations.extend(lm_recs)
            except Exception as exc:
                logger.debug("Failed to parse agent advisor recommendation: %s", exc)

        confidence = 1.0 - (len(problem_traces) / max(len(traces), 1))
        return {
            "recommendations": recommendations,
            "confidence": round(confidence, 2),
            "analyzed_traces": len(traces),
            "problem_traces": len(problem_traces),
        }

    def _analyze_patterns(self, traces: List[Any]) -> List[Dict[str, Any]]:
        """Structural analysis of trace patterns."""
        recs: List[Dict[str, Any]] = []

        # Check for excessive tool calls
        tool_heavy = [
            t
            for t in traces
            if sum(1 for s in (t.steps or []) if s.step_type.value == "tool_call")
            > 5
        ]
        if len(tool_heavy) > len(traces) * 0.3:
            recs.append(
                {
                    "type": "agent_structure",
                    "suggestion": (
                        "Reduce tool call frequency"
                        " — many traces have >5 tool calls"
                    ),
                    "severity": "medium",
                }
            )

        # Check for repeated failures on same query type
        failure_classes: Dict[str, int] = {}
        for t in traces:
            if t.outcome != "success":
                qclass = self._classify(t.query)
                failure_classes[qclass] = failure_classes.get(qclass, 0) + 1
        for qclass, count in failure_classes.items():
            if count >= 3:
                recs.append(
                    {
                        "type": "routing",
                        "suggestion": (
                            f"Query class '{qclass}' has {count}"
                            " failures — consider different model or agent"
                        ),
                        "severity": "high",
                    }
                )

        return recs

    @staticmethod
    def _classify(query: str) -> str:
        q = query.lower()
        if any(kw in q for kw in ("def ", "class ", "import ")):
            return "code"
        if any(kw in q for kw in ("solve", "equation")):
            return "math"
        return "general"

    def _get_lm_recommendations(self, traces: List[Any]) -> List[Dict[str, Any]]:
        """Get LM-guided recommendations (requires advisor engine)."""
        from openjarvis.core.types import Message, Role

        summaries = []
        for t in traces[:10]:
            summary = (
                f"Query: {t.query[:100]}, "
                f"Outcome: {t.outcome}, "
                f"Latency: {t.total_latency_seconds:.1f}s, "
                f"Steps: {len(t.steps or [])}"
            )
            summaries.append(summary)

        prompt = (
            "Analyze these agent interaction traces and suggest improvements:\n\n"
            + "\n".join(summaries)
            + "\n\nProvide 1-3 specific recommendations."
        )
        messages = [Message(role=Role.USER, content=prompt)]
        result = self._advisor_engine.generate(
            messages,
            model=self._advisor_model,
        )
        content = result.get("content", "")
        return [{"type": "lm_guided", "suggestion": content, "severity": "info"}]


__all__ = ["AgentAdvisorPolicy"]
