"""Learned router policy — trace-driven query_class/task_class -> lane/model mapping.

Merges the runtime ``select_model()`` logic from ``TraceDrivenPolicy``
with the batch ``update()`` logic from ``SFTRouterPolicy`` into a single
class registered as ``"learned"`` in ``RouterPolicyRegistry``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from openjarvis.core.registry import RouterPolicyRegistry
from openjarvis.core.types import RoutingContext
from openjarvis.learning._stubs import RouterPolicy
from openjarvis.learning.routing._utils import classify_query
from openjarvis.learning.routing.router import lane_for_model

logger = logging.getLogger(__name__)


class LearnedRouterPolicy(RouterPolicy):
    """Trace-driven router that learns query_class -> model mappings.

    Implements ``RouterPolicy.select_model()`` for runtime routing AND
    provides ``update_from_traces()`` / ``observe()`` for learning from traces,
    plus ``update()`` for batch learning from a trace store.
    """

    def __init__(
        self,
        analyzer: Optional[Any] = None,
        *,
        available_models: Optional[List[str]] = None,
        default_model: str = "",
        fallback_model: str = "",
    ) -> None:
        self._analyzer = analyzer
        self._available = available_models or []
        self._default = default_model
        self._fallback = fallback_model
        self._policy_map: Dict[str, str] = {}
        self._confidence: Dict[str, int] = {}
        self._lane_policy_map: Dict[str, str] = {}
        self._lane_confidence: Dict[str, int] = {}
        self.min_samples: int = 5

    @property
    def policy_map(self) -> Dict[str, str]:
        """Current learned routing decisions (read-only copy)."""
        return dict(self._policy_map)

    def select_model(self, context: RoutingContext) -> str:
        """Select the best model based on learned policy or fallback."""
        task_key = self._context_key(context)

        if (
            task_key in self._lane_policy_map
            and self._lane_confidence.get(task_key, 0) >= self.min_samples
        ):
            lane = self._lane_policy_map[task_key]
            lane_model = self._select_available_model_for_lane(lane)
            if lane_model:
                return lane_model

        query_class = classify_query(context.query)

        if (
            query_class in self._policy_map
            and self._confidence.get(query_class, 0) >= self.min_samples
        ):
            model = self._policy_map[query_class]
            if not self._available or model in self._available:
                return model

        avail = self._available
        if self._default and (not avail or self._default in avail):
            return self._default
        if self._fallback and (not avail or self._fallback in avail):
            return self._fallback
        if self._available:
            return self._available[0]
        return self._default or ""

    @property
    def lane_policy_map(self) -> Dict[str, str]:
        """Current learned lane preferences (read-only copy)."""
        return dict(self._lane_policy_map)

    def update_from_traces(
        self,
        *,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Recompute the policy map from trace history via TraceAnalyzer."""
        if self._analyzer is None:
            return {"error": "no analyzer configured"}

        traces = self._analyzer._store.list_traces(
            since=since, until=until, limit=10_000
        )
        if not traces:
            return {"updated": False, "reason": "no traces"}

        groups: Dict[str, list] = {}
        for t in traces:
            key = self._trace_key(t)
            groups.setdefault(key, []).append(t)

        old_map = dict(self._policy_map)
        old_lane_map = dict(self._lane_policy_map)
        changes: Dict[str, Dict[str, str]] = {}
        lane_changes: Dict[str, Dict[str, str]] = {}

        for route_key, class_traces in groups.items():
            model_scores: Dict[str, _ModelScore] = {}
            lane_scores: Dict[str, _ModelScore] = {}
            for t in class_traces:
                if not t.model:
                    continue
                if t.model not in model_scores:
                    model_scores[t.model] = _ModelScore()
                score = model_scores[t.model]
                self._apply_trace_score(score, t)

                lane = self._trace_lane(t) or lane_for_model(t.model)
                if lane:
                    if lane not in lane_scores:
                        lane_scores[lane] = _ModelScore()
                    self._apply_trace_score(lane_scores[lane], t)

            if not model_scores:
                continue

            best_model = max(
                model_scores.items(),
                key=lambda kv: kv[1].composite_score(),
            )[0]

            self._policy_map[route_key] = best_model
            self._confidence[route_key] = sum(s.count for s in model_scores.values())

            if old_map.get(route_key) != best_model:
                changes[route_key] = {
                    "old": old_map.get(route_key, ""),
                    "new": best_model,
                }

            if lane_scores:
                best_lane = max(
                    lane_scores.items(),
                    key=lambda kv: kv[1].composite_score(),
                )[0]
                self._lane_policy_map[route_key] = best_lane
                self._lane_confidence[route_key] = sum(
                    s.count for s in lane_scores.values()
                )
                if old_lane_map.get(route_key) != best_lane:
                    lane_changes[route_key] = {
                        "old": old_lane_map.get(route_key, ""),
                        "new": best_lane,
                    }

        return {
            "updated": True,
            "query_classes": len(groups),
            "total_traces": len(traces),
            "changes": changes,
            "lane_changes": lane_changes,
        }

    def observe(
        self,
        query: str,
        model: str,
        outcome: Optional[str],
        feedback: Optional[float],
    ) -> None:
        """Record a single observation for online (incremental) updates."""
        qclass = classify_query(query)
        current_count = self._confidence.get(qclass, 0)

        if qclass not in self._policy_map:
            self._policy_map[qclass] = model
            self._confidence[qclass] = 1
            return

        self._confidence[qclass] = current_count + 1

        if outcome == "success" and feedback is not None and feedback > 0.7:
            if current_count < self.min_samples:
                self._policy_map[qclass] = model

    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        """Batch update: analyze trace outcomes and update the policy map.

        This is the batch learning interface (from the old SFTRouterPolicy).
        """
        try:
            traces = trace_store.list_traces()
        except Exception as exc:
            logger.warning("Learned router update failed: %s", exc)
            return {"updated": False, "reason": "Could not access trace store"}

        class_model_scores: Dict[str, Dict[str, List[float]]] = {}
        class_lane_scores: Dict[str, Dict[str, List[float]]] = {}
        for trace in traces:
            query_class = self._trace_key(trace)
            model = trace.model or "unknown"
            composite = self._trace_composite_score(trace)

            if query_class not in class_model_scores:
                class_model_scores[query_class] = {}
            if model not in class_model_scores[query_class]:
                class_model_scores[query_class][model] = []
            class_model_scores[query_class][model].append(composite)

            lane = self._trace_lane(trace) or lane_for_model(model)
            if lane:
                if query_class not in class_lane_scores:
                    class_lane_scores[query_class] = {}
                if lane not in class_lane_scores[query_class]:
                    class_lane_scores[query_class][lane] = []
                class_lane_scores[query_class][lane].append(composite)

        changes = {}
        for qclass, model_scores in class_model_scores.items():
            best_model = None
            best_score = -1.0
            for model, scores in model_scores.items():
                if len(scores) >= self.min_samples:
                    avg = sum(scores) / len(scores)
                    if avg > best_score:
                        best_score = avg
                        best_model = model
            if best_model and best_model != self._policy_map.get(qclass):
                self._policy_map[qclass] = best_model
                changes[qclass] = best_model

        lane_changes = {}
        for qclass, lane_scores in class_lane_scores.items():
            best_lane = None
            best_score = -1.0
            for lane, scores in lane_scores.items():
                if len(scores) >= self.min_samples:
                    avg = sum(scores) / len(scores)
                    if avg > best_score:
                        best_score = avg
                        best_lane = lane
            if best_lane and best_lane != self._lane_policy_map.get(qclass):
                self._lane_policy_map[qclass] = best_lane
                lane_changes[qclass] = best_lane

        return {
            "updated": bool(changes),
            "changes": changes,
            "lane_policy_map": dict(self._lane_policy_map),
            "lane_changes": lane_changes,
            "policy_map": dict(self._policy_map),
        }

    def _context_key(self, context: RoutingContext) -> str:
        return context.task_class or classify_query(context.query)

    def _trace_key(self, trace: Any) -> str:
        routing = self._trace_routing(trace)
        return str(routing.get("task_class") or classify_query(trace.query))

    def _trace_lane(self, trace: Any) -> str:
        routing = self._trace_routing(trace)
        return str(routing.get("lane") or "")

    def _trace_routing(self, trace: Any) -> Dict[str, Any]:
        metadata = getattr(trace, "metadata", {}) or {}
        routing = metadata.get("routing")
        if isinstance(routing, dict):
            return routing
        for step in getattr(trace, "steps", []) or []:
            step_type = getattr(step, "step_type", None)
            if getattr(step_type, "value", step_type) == "route":
                return {
                    **(getattr(step, "input", {}) or {}),
                    **(getattr(step, "output", {}) or {}),
                    **(getattr(step, "metadata", {}) or {}),
                }
        return {}

    def _trace_composite_score(self, trace: Any) -> float:
        outcome_score = 1.0 if trace.outcome == "success" else 0.0
        fb = trace.feedback if trace.feedback is not None else 0.5
        routing = self._trace_routing(trace)
        escalation_penalty = 0.0
        escalation_chain = routing.get("escalation_chain") or []
        if isinstance(escalation_chain, list) and len(escalation_chain) > 1:
            escalation_penalty = min(0.15, 0.03 * (len(escalation_chain) - 1))
        return max(0.0, 0.6 * outcome_score + 0.4 * fb - escalation_penalty)

    def _apply_trace_score(self, score: "_ModelScore", trace: Any) -> None:
        score.count += 1
        score.total_latency += trace.total_latency_seconds
        if trace.outcome == "success":
            score.successes += 1
        if trace.feedback is not None:
            score.feedback_sum += trace.feedback
            score.feedback_count += 1
        routing = self._trace_routing(trace)
        escalation_chain = routing.get("escalation_chain") or []
        if isinstance(escalation_chain, list) and len(escalation_chain) > 1:
            score.penalty += min(0.15, 0.03 * (len(escalation_chain) - 1))

    def _select_available_model_for_lane(self, lane: str) -> str:
        candidates = self._available or [m for m in [self._default, self._fallback] if m]
        for model in candidates:
            if lane_for_model(model) == lane:
                return model
        return ""


class _ModelScore:
    """Accumulator for per-model scoring during policy update."""

    __slots__ = (
        "count",
        "successes",
        "total_latency",
        "feedback_sum",
        "feedback_count",
        "penalty",
    )

    def __init__(self) -> None:
        self.count = 0
        self.successes = 0
        self.total_latency = 0.0
        self.feedback_sum = 0.0
        self.feedback_count = 0
        self.penalty = 0.0

    def composite_score(self) -> float:
        """Weighted score combining success rate and feedback."""
        sr = self.successes / self.count if self.count else 0.0
        fb = self.feedback_sum / self.feedback_count if self.feedback_count else 0.5
        avg_penalty = self.penalty / self.count if self.count else 0.0
        return max(0.0, 0.6 * sr + 0.4 * fb - avg_penalty)


def ensure_registered() -> None:
    """Register LearnedRouterPolicy if not already present."""
    if not RouterPolicyRegistry.contains("learned"):
        RouterPolicyRegistry.register_value("learned", LearnedRouterPolicy)


ensure_registered()

__all__ = ["LearnedRouterPolicy", "ensure_registered"]
