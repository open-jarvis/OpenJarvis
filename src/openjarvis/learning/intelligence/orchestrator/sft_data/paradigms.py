"""Render a canonical ADP ``Episode`` under each local↔cloud paradigm.

Each renderer assigns a model **tier** to every step according to that
paradigm's policy, attaches the estimated telemetry (cost/energy/latency/power)
to the step's observation, and predicts whether the rendering would still solve
the task. Selection (``select.py``) then keeps the cheapest predicted-correct
rendering per task.

These are the cold-start *tiering* scaffolds of the real
``agents/hybrid/*`` paradigms — same names, same local-first spirit, no live
execution. Swapping in real runs is the v2 item in the design doc.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable, List

from openjarvis.learning.intelligence.orchestrator.sft_data.tiers import (
    Difficulty,
    Tier,
    covers,
    min_covering_tier,
    step_difficulty,
    tier_name,
    tier_telemetry,
)
from openjarvis.learning.intelligence.orchestrator.types import Episode

# Detected in an observation -> the demonstration had to retry -> harder task.
_RETRY_MARKERS = (
    "your answer is wrong",
    "incorrect",
    "traceback",
    "error:",
    "failed",
    "try again",
)


@dataclass
class RenderedEpisode:
    """An ``Episode`` re-tiered under one paradigm, plus its prediction."""

    paradigm: str
    episode: Episode
    """Deep copy with per-step tier in ``action.tool_name`` and telemetry filled."""

    step_tiers: List[str] = field(default_factory=list)
    """Tier key (``local``/``mid``/``frontier``/``search``) chosen per step."""

    predicted_correct: bool = False


def _difficulties(episode: Episode) -> List[Difficulty]:
    """Per-step difficulty, with a trajectory-wide retry bump."""
    retry = any(
        any(m in (step.observation.content or "").lower() for m in _RETRY_MARKERS)
        for step in episode.steps
    )
    out: List[Difficulty] = []
    for step in episode.steps:
        kind = step.action.tool_name
        out.append(step_difficulty(kind, step.action.tool_input, retry_signal=retry))
    return out


def _apply(
    episode: Episode,
    paradigm: str,
    tier_keys: List[str],
    predicted_correct: bool,
) -> RenderedEpisode:
    """Build a RenderedEpisode: stamp each step with its tier + telemetry."""
    ep = copy.deepcopy(episode)
    ep.total_cost_usd = 0.0
    ep.total_energy_joules = 0.0
    ep.total_latency_seconds = 0.0
    ep.total_tokens = 0
    ep.max_power_watts = 0.0

    for step, tier_key in zip(ep.steps, tier_keys):
        tel = tier_telemetry(tier_key)
        step.observation.cost_usd = tel["cost_usd"]
        step.observation.energy_joules = tel["energy_joules"]
        step.observation.latency_seconds = tel["latency_seconds"]
        step.observation.power_watts = tel["power_watts"]
        step.observation.tokens = int(tel["tokens"])
        # Record the routing decision on the action for the serializer.
        step.action.thought = _thought_for(tier_key, step.action.tool_name)
        ep.total_cost_usd += tel["cost_usd"]
        ep.total_energy_joules += tel["energy_joules"]
        ep.total_latency_seconds += tel["latency_seconds"]
        ep.total_tokens += int(tel["tokens"])
        ep.max_power_watts = max(ep.max_power_watts, tel["power_watts"])

    ep.correct = predicted_correct
    ep.metadata["paradigm"] = paradigm
    return RenderedEpisode(
        paradigm=paradigm,
        episode=ep,
        step_tiers=tier_keys,
        predicted_correct=predicted_correct,
    )


def _thought_for(tier_key: str, kind: str) -> str:
    if kind == "search" or tier_key == "search":
        return "This step needs retrieval; route to web_search."
    reason = {
        "local": "Cheap and on-device; the local model can handle this step.",
        "mid": "Beyond easy; escalate to a cheap mid-tier cloud model.",
        "frontier": "Hard step; escalate to the frontier cloud model.",
    }[tier_key]
    return reason


def _tier_key_for_step(kind: str, tier: Tier) -> str:
    return "search" if kind == "search" else tier_name(tier)


# --- paradigm renderers -----------------------------------------------------


def render_baseline_local(episode: Episode) -> RenderedEpisode:
    diffs = _difficulties(episode)
    tiers = [
        _tier_key_for_step(s.action.tool_name, Tier.LOCAL) for s in episode.steps
    ]
    predicted = all(d == Difficulty.EASY for d in diffs)
    return _apply(episode, "baseline_local", tiers, predicted)


def render_baseline_cloud(episode: Episode) -> RenderedEpisode:
    tiers = [
        _tier_key_for_step(s.action.tool_name, Tier.FRONTIER) for s in episode.steps
    ]
    return _apply(episode, "baseline_cloud", tiers, True)


def render_advisor(episode: Episode) -> RenderedEpisode:
    """Local executor, frontier rewrite of the final answer."""
    diffs = _difficulties(episode)
    tiers: List[str] = []
    n = len(episode.steps)
    for i, s in enumerate(episode.steps):
        tier = Tier.FRONTIER if i == n - 1 else Tier.LOCAL
        tiers.append(_tier_key_for_step(s.action.tool_name, tier))
    predicted = all(d == Difficulty.EASY for d in diffs[:-1]) if n > 1 else True
    return _apply(episode, "advisor", tiers, predicted)


def render_toolorchestra(episode: Episode) -> RenderedEpisode:
    """Local-first per-step: assign each step its minimum covering tier."""
    diffs = _difficulties(episode)
    tiers = [
        _tier_key_for_step(s.action.tool_name, min_covering_tier(d))
        for s, d in zip(episode.steps, diffs)
    ]
    predicted = all(
        covers(min_covering_tier(d), d) for d in diffs
    )  # True by construction
    return _apply(episode, "toolorchestra", tiers, predicted)


PARADIGMS: dict[str, Callable[[Episode], RenderedEpisode]] = {
    "baseline_local": render_baseline_local,
    "baseline_cloud": render_baseline_cloud,
    "advisor": render_advisor,
    "toolorchestra": render_toolorchestra,
}


def render_all(episode: Episode) -> List[RenderedEpisode]:
    """Render ``episode`` under every paradigm."""
    return [render(episode) for render in PARADIGMS.values()]


__all__ = [
    "PARADIGMS",
    "RenderedEpisode",
    "render_advisor",
    "render_all",
    "render_baseline_cloud",
    "render_baseline_local",
    "render_toolorchestra",
]
