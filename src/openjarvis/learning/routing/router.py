"""Heuristic model router — selects models via task class and capability lanes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import RoutingContext, StepType
from openjarvis.learning._stubs import QueryAnalyzer, RouterPolicy
from openjarvis.learning.routing.task_classifier import classify_task

logger = logging.getLogger(__name__)

LANE_ROUTER_CONTROL = "router_control"
LANE_FREE_FALLBACK = "free_fallback"
LANE_CHEAP_PAID_WORKHORSE = "cheap_paid_workhorse"
LANE_PREMIUM_WORKHORSE = "premium_workhorse"
LANE_FRONTIER_PREMIUM = "frontier_premium"
LANE_CODE_SPECIALIST = "code_specialist"
LANE_LONG_CONTEXT_RESEARCH = "long_context_research"
LANE_MULTIMODAL_VISION = "multimodal_vision"

_LANE_ESCALATION_ORDER = {
    LANE_ROUTER_CONTROL: [
        LANE_ROUTER_CONTROL,
        LANE_CHEAP_PAID_WORKHORSE,
        LANE_PREMIUM_WORKHORSE,
        LANE_FRONTIER_PREMIUM,
    ],
    LANE_FREE_FALLBACK: [
        LANE_FREE_FALLBACK,
        LANE_CHEAP_PAID_WORKHORSE,
        LANE_PREMIUM_WORKHORSE,
        LANE_FRONTIER_PREMIUM,
    ],
    LANE_CHEAP_PAID_WORKHORSE: [
        LANE_CHEAP_PAID_WORKHORSE,
        LANE_PREMIUM_WORKHORSE,
        LANE_FRONTIER_PREMIUM,
    ],
    LANE_PREMIUM_WORKHORSE: [LANE_PREMIUM_WORKHORSE, LANE_FRONTIER_PREMIUM],
    LANE_FRONTIER_PREMIUM: [LANE_FRONTIER_PREMIUM],
    LANE_CODE_SPECIALIST: [
        LANE_CODE_SPECIALIST,
        LANE_PREMIUM_WORKHORSE,
        LANE_FRONTIER_PREMIUM,
    ],
    LANE_LONG_CONTEXT_RESEARCH: [
        LANE_LONG_CONTEXT_RESEARCH,
        LANE_PREMIUM_WORKHORSE,
        LANE_FRONTIER_PREMIUM,
    ],
    LANE_MULTIMODAL_VISION: [
        LANE_MULTIMODAL_VISION,
        LANE_PREMIUM_WORKHORSE,
        LANE_FRONTIER_PREMIUM,
    ],
}


@dataclass(frozen=True)
class RouteDecision:
    lane: str
    model: str
    candidate_models: List[str]
    escalation_chain: List[str]
    reason: str


def build_routing_context(
    query: str, *, urgency: float = 0.5, model: str | None = None
) -> RoutingContext:
    """Populate a ``RoutingContext`` from a raw query string.

    When *model* is provided, the suggested token budget is adjusted
    for thinking models that need extra headroom.
    """
    from openjarvis.learning.routing.complexity import (
        adjust_tokens_for_model,
        score_complexity,
    )

    result = score_complexity(query)
    tokens = adjust_tokens_for_model(result.suggested_max_tokens, model)
    task = classify_task(query)
    vision_required = bool(result.signals.get("has_vision", False)) or any(
        token in query.lower() for token in ("image", "screenshot", "diagram", "pdf")
    )
    estimated_context_tokens = max(256, len(query) // 4)

    return RoutingContext(
        query=query,
        query_length=len(query),
        has_code=result.signals.get("has_code", False),
        has_math=result.signals.get("has_math", False),
        has_reasoning=result.signals.get("has_reasoning", False),
        urgency=urgency,
        complexity_score=result.score,
        suggested_max_tokens=tokens,
        task_class=task.task_class,
        task_class_confidence=task.confidence,
        vision_required=vision_required,
        estimated_context_tokens=estimated_context_tokens,
        metadata={
            "complexity_tier": result.tier,
            "signals": result.signals,
        },
    )


def _model_size(key: str) -> float:
    try:
        spec = ModelRegistry.get(key)
        return spec.parameter_count_b
    except (KeyError, AttributeError) as exc:
        logger.debug("Failed to compute model score: %s", exc)
        return 0.0


def _model_spec(key: str):
    try:
        return ModelRegistry.get(key)
    except Exception:
        return None


def _find_model_by_tag(available: List[str], tag: str) -> Optional[str]:
    tag_lower = tag.lower()
    for key in available:
        if tag_lower in key.lower():
            return key
    return None


def _largest_model(available: List[str]) -> Optional[str]:
    if not available:
        return None
    best = available[0]
    best_size = _model_size(best)
    for key in available[1:]:
        size = _model_size(key)
        if size > best_size:
            best = key
            best_size = size
    return best


def _smallest_model(available: List[str]) -> Optional[str]:
    if not available:
        return None
    best = available[0]
    best_size = _model_size(best) or float("inf")
    for key in available[1:]:
        size = _model_size(key)
        if 0 < size < best_size:
            best = key
            best_size = size
    return best


def _lane_for_context(context: RoutingContext) -> str:
    task_class = context.task_class or classify_task(context.query).task_class
    if context.vision_required:
        return LANE_MULTIMODAL_VISION
    if task_class in {"classify", "extract"}:
        return LANE_ROUTER_CONTROL
    if task_class in {
        "code-simple",
        "code-medium",
        "debug-simple",
        "test-generation",
        "refactor",
    }:
        return LANE_CODE_SPECIALIST
    if task_class in {"code-complex", "debug-complex", "architecture-review"}:
        return LANE_PREMIUM_WORKHORSE
    if task_class in {
        "source-finding",
        "source-reading",
        "synthesis",
        "citation-building",
        "trend-detection",
        "competitor-mapping",
    }:
        if context.estimated_context_tokens >= 4000 or context.complexity_score >= 0.6:
            return LANE_LONG_CONTEXT_RESEARCH
        return LANE_CHEAP_PAID_WORKHORSE
    if context.budget_sensitivity == "high" and context.risk_level == "low":
        return LANE_FREE_FALLBACK
    if context.complexity_score >= 0.85 and context.risk_level in {"high", "critical"}:
        return LANE_FRONTIER_PREMIUM
    if context.complexity_score >= 0.55 or context.has_reasoning:
        return LANE_PREMIUM_WORKHORSE
    return LANE_CHEAP_PAID_WORKHORSE


def _spec_lane(model_id: str) -> str:
    spec = _model_spec(model_id)
    if spec is not None:
        lane = spec.metadata.get("routing_lane")
        if isinstance(lane, str) and lane:
            return lane
    lower = model_id.lower()
    if (
        lower.startswith("openrouter/free")
        or lower == "openrouter/free"
        or ":free" in lower
    ):
        return LANE_FREE_FALLBACK
    if lower.startswith("openrouter/"):
        if any(tag in lower for tag in ("vl", "vision", "maverick")):
            return LANE_MULTIMODAL_VISION
        if any(tag in lower for tag in ("coder", "code")):
            return LANE_CODE_SPECIALIST
        if any(tag in lower for tag in ("opus", "fable", "gpt-5.5")):
            return LANE_FRONTIER_PREMIUM
        if any(tag in lower for tag in ("scout", "long", "80b-a3b-thinking")):
            return LANE_LONG_CONTEXT_RESEARCH
        return LANE_CHEAP_PAID_WORKHORSE
    if any(tag in lower for tag in ("coder", "code")):
        return LANE_CODE_SPECIALIST
    if lower in {"qwen2.5:1.5b", "llama3.2:1b"}:
        return LANE_ROUTER_CONTROL
    if any(tag in lower for tag in ("vision", "vl")):
        return LANE_MULTIMODAL_VISION
    if any(tag in lower for tag in ("phi4-mini-reasoning", "reasoning", "32b", "70b")):
        return LANE_PREMIUM_WORKHORSE
    return LANE_CHEAP_PAID_WORKHORSE


def lane_for_model(model_id: str) -> str:
    """Public helper that maps a model id to its routing lane."""
    return _spec_lane(model_id)


def _filter_by_lane(available: Iterable[str], lane: str) -> List[str]:
    return [model for model in available if _spec_lane(model) == lane]


def escalation_chain_for_lane(lane: str) -> List[str]:
    return list(_LANE_ESCALATION_ORDER.get(lane, [lane]))


def _prefer_local(models: List[str]) -> List[str]:
    def rank(model: str) -> tuple[int, float, str]:
        spec = _model_spec(model)
        engines = tuple(spec.supported_engines) if spec is not None else ()
        local = (
            0
            if any(
                e in engines
                for e in ("ollama", "llamacpp", "vllm", "mlx", "sglang")
            )
            else 1
        )
        size = _model_size(model) or 0.0
        return (local, size, model)

    return sorted(models, key=rank)


def explain_route(
    context: RoutingContext,
    *,
    available_models: List[str] | None = None,
    default_model: str = "",
    fallback_model: str = "",
) -> RouteDecision:
    router = HeuristicRouter(
        available_models=available_models,
        default_model=default_model,
        fallback_model=fallback_model,
    )
    available = router.available_models or list(ModelRegistry.keys())
    selected_lane = context.lane or _lane_for_context(context)
    candidates = _prefer_local(_filter_by_lane(available, selected_lane))
    selected_model = router.select_model(context)
    if not candidates and selected_model:
        candidates = [selected_model]
    reason = (
        f"task_class={context.task_class or 'unknown'} "
        f"complexity={context.complexity_score:.3f} lane={selected_lane}"
    )
    return RouteDecision(
        lane=selected_lane,
        model=selected_model,
        candidate_models=candidates,
        escalation_chain=escalation_chain_for_lane(selected_lane),
        reason=reason,
    )


def emit_route_trace(
    bus: EventBus | None,
    *,
    context: RoutingContext,
    decision: RouteDecision,
    selected_model: str,
    selected_engine: str,
    failure_reason: str | None = None,
) -> None:
    """Publish a standardized route trace event when a bus is available."""
    if bus is None:
        return
    metadata = {"reason": decision.reason}
    if failure_reason:
        metadata["failure_reason"] = failure_reason
    bus.publish(
        EventType.TRACE_STEP,
        {
            "step_type": StepType.ROUTE.value,
            "input": {
                "query": context.query,
                "task_class": context.task_class,
            },
            "output": {
                "lane": decision.lane,
                "model": selected_model,
                "candidate_models": decision.candidate_models,
                "escalation_chain": decision.escalation_chain,
                "selected_engine": selected_engine,
            },
            "metadata": metadata,
        },
    )


class HeuristicRouter(RouterPolicy):
    """Rule-based model router with Pass-1 lane awareness.

    New flow:
    1. Determine task class / lane from ``RoutingContext``.
    2. Choose the cheapest adequate model inside that lane.
    3. Fall back to the legacy small/large/coder heuristics if no lane candidate exists.
    """

    def __init__(
        self,
        available_models: List[str] | None = None,
        *,
        default_model: str = "",
        fallback_model: str = "",
    ) -> None:
        self._available = available_models or []
        self._default = default_model
        self._fallback = fallback_model

    @property
    def available_models(self) -> List[str]:
        return list(self._available)

    def select_model(self, context: RoutingContext) -> str:
        available = self._available or list(ModelRegistry.keys())
        if not available:
            return self._default or self._fallback or ""

        use_lane_routing = bool(
            context.lane
            or context.task_class
            or context.vision_required
            or context.budget_sensitivity != "medium"
            or context.risk_level != "low"
            or context.latency_sensitivity != "medium"
            or context.required_confidence is not None
            or context.estimated_context_tokens > 0
        )
        if use_lane_routing:
            lane = context.lane or _lane_for_context(context)
            lane_candidates = _filter_by_lane(available, lane)
            if lane_candidates:
                lane_candidates = _prefer_local(lane_candidates)
                if lane == LANE_ROUTER_CONTROL:
                    return _smallest_model(lane_candidates) or lane_candidates[0]
                if lane == LANE_FREE_FALLBACK:
                    free = _find_model_by_tag(
                        lane_candidates, ":free"
                    ) or _find_model_by_tag(lane_candidates, "openrouter/free")
                    return free or lane_candidates[0]
                if lane == LANE_CODE_SPECIALIST:
                    code_model = _find_model_by_tag(
                        lane_candidates, "code"
                    ) or _find_model_by_tag(lane_candidates, "coder")
                    return code_model or (
                        _smallest_model(lane_candidates) or lane_candidates[0]
                    )
                if lane == LANE_LONG_CONTEXT_RESEARCH:
                    return _largest_model(lane_candidates) or lane_candidates[0]
                if lane in {LANE_PREMIUM_WORKHORSE, LANE_FRONTIER_PREMIUM}:
                    return _largest_model(lane_candidates) or lane_candidates[0]
                return _smallest_model(lane_candidates) or lane_candidates[0]

        # Legacy fallback path.
        if context.urgency > 0.8:
            return _smallest_model(available) or available[0]
        if context.has_code:
            code_model = _find_model_by_tag(available, "code") or _find_model_by_tag(
                available, "coder"
            )
            if code_model:
                return code_model
            return _largest_model(available) or available[0]
        if context.has_math:
            return _largest_model(available) or available[0]
        if context.complexity_score < 0.20:
            return _smallest_model(available) or available[0]
        if context.complexity_score >= 0.55 or context.has_reasoning:
            return _largest_model(available) or available[0]
        if self._default and self._default in available:
            return self._default
        if self._fallback and self._fallback in available:
            return self._fallback
        return available[0]


class DefaultQueryAnalyzer(QueryAnalyzer):
    """Default query analyzer wrapping the heuristic build_routing_context function."""

    def analyze(self, query: str, **kwargs: object) -> RoutingContext:
        urgency = kwargs.get("urgency", 0.5)
        if not isinstance(urgency, (int, float)):
            urgency = 0.5
        model = kwargs.get("model")
        if not isinstance(model, str):
            model = None
        context = build_routing_context(query, urgency=urgency, model=model)
        for attr in (
            "risk_level",
            "latency_sensitivity",
            "budget_sensitivity",
            "required_confidence",
            "interactive",
        ):
            if attr in kwargs and hasattr(context, attr):
                setattr(context, attr, kwargs[attr])
        if "vision_required" in kwargs:
            context.vision_required = bool(kwargs["vision_required"])
        return context


__all__ = [
    "DefaultQueryAnalyzer",
    "HeuristicRouter",
    "LANE_CHEAP_PAID_WORKHORSE",
    "LANE_CODE_SPECIALIST",
    "LANE_FREE_FALLBACK",
    "LANE_FRONTIER_PREMIUM",
    "LANE_LONG_CONTEXT_RESEARCH",
    "LANE_MULTIMODAL_VISION",
    "LANE_PREMIUM_WORKHORSE",
    "LANE_ROUTER_CONTROL",
    "RouteDecision",
    "build_routing_context",
    "escalation_chain_for_lane",
    "emit_route_trace",
    "explain_route",
    "lane_for_model",
]
