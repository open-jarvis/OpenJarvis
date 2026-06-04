"""Model tiers, per-tier telemetry estimates, and step-difficulty heuristics.

This is the *one estimate* of the cold-start (see the design doc): because we
do not execute models, we approximate "what would this step cost on tier X?"
with flat per-tier telemetry, and "how hard is this step?" with a heuristic over
the ADP step kind and the trajectory's retry signals.

Costs reuse the authoritative hybrid pricing table so the orchestrator is
trained against the same dollars the paradigm harness charges.
"""

from __future__ import annotations

from enum import IntEnum

from openjarvis.agents.hybrid import _prices

# Representative model per tier (drives the $ side of telemetry).
TIER_MODEL: dict[str, str] = {
    "local": "qwen3:8b",  # local vLLM -> unknown to PRICES -> $0
    "mid": "gemini-2.5-flash",
    "frontier": "claude-sonnet-4-6",
    "search": "qwen3:8b",  # retrieval is a tool call, not a model tier
}

# Rough token budgets per step kind, for the cost estimate.
_TOKENS_IN = 800
_TOKENS_OUT = {"local": 400, "mid": 400, "frontier": 600, "search": 80}

# Non-$ telemetry per step (joules / seconds / watts). Local work burns some
# on-device energy/power but no dollars; cloud work is ~free locally but costs
# dollars and adds latency. Tuned (against reward.py's default weights and
# normalizers) so the local-first ordering holds: on a step a tier can cover,
# local beats cloud, and per-step escalation beats all-frontier. These are the
# tunable knobs of the cold-start estimate — see the design doc.
_ENERGY_J = {"local": 5.0, "mid": 0.5, "frontier": 0.5, "search": 0.2}
_LATENCY_S = {"local": 1.5, "mid": 1.5, "frontier": 4.0, "search": 1.0}
_POWER_W = {"local": 20.0, "mid": 5.0, "frontier": 5.0, "search": 5.0}
_SEARCH_COST_USD = 0.001


class Tier(IntEnum):
    """Model capability tier; ordered so a higher tier covers a harder step."""

    LOCAL = 0
    MID = 1
    FRONTIER = 2


class Difficulty(IntEnum):
    """Estimated step difficulty; compared against :class:`Tier` rank."""

    EASY = 0
    MED = 1
    HARD = 2


_TIER_NAME = {Tier.LOCAL: "local", Tier.MID: "mid", Tier.FRONTIER: "frontier"}


def tier_name(tier: Tier) -> str:
    return _TIER_NAME[tier]


def tier_telemetry(tier_key: str) -> dict[str, float]:
    """Estimated ``(cost, energy, latency, power, tokens)`` for one step at a tier.

    ``tier_key`` is one of ``local``/``mid``/``frontier``/``search``.
    """
    out_tokens = _TOKENS_OUT[tier_key]
    if tier_key == "search":
        cost = _SEARCH_COST_USD
    else:
        cost = _prices.cost(TIER_MODEL[tier_key], _TOKENS_IN, out_tokens)
    return {
        "cost_usd": cost,
        "energy_joules": _ENERGY_J[tier_key],
        "latency_seconds": _LATENCY_S[tier_key],
        "power_watts": _POWER_W[tier_key],
        "tokens": float(_TOKENS_IN + out_tokens),
    }


def step_difficulty(
    kind: str, content: str, *, retry_signal: bool = False
) -> Difficulty:
    """Heuristic difficulty for a canonical step.

    - ``code`` actions are at least MED (real execution / logic).
    - very long actions, or any step in a trajectory that hit a retry signal
      ("your answer is wrong" etc.), bump to HARD.
    - everything else (plain messages / short reasoning) is EASY.
    """
    base = Difficulty.MED if kind == "code" else Difficulty.EASY
    if retry_signal or len(content) > 1500:
        return Difficulty.HARD
    return base


def covers(tier: Tier, difficulty: Difficulty) -> bool:
    """True iff ``tier`` is capable enough for a step of this ``difficulty``."""
    return int(tier) >= int(difficulty)


def min_covering_tier(difficulty: Difficulty) -> Tier:
    """The cheapest tier that still covers ``difficulty`` (local-first optimum)."""
    return Tier(int(difficulty))


__all__ = [
    "Difficulty",
    "Tier",
    "TIER_MODEL",
    "covers",
    "min_covering_tier",
    "step_difficulty",
    "tier_name",
    "tier_telemetry",
]
