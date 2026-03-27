"""Savings calculation — compare local inference cost against cloud providers.

FLOPs and energy use a no-KV-cache model: P * N * (N+1) where P = params,
N = total tokens. This reflects full recompute without cached attention.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

# Bump when token-counting methodology changes so that the leaderboard
# can distinguish entries computed under different rules.
#   v1 = original (Ollama prompt_eval_count, may under-count due to KV cache)
#   v2 = full prompt token count, no KV-cache assumption, system prompt always counted
TOKEN_COUNTING_VERSION: int = 2

# ---------------------------------------------------------------------------
# Cloud provider pricing (USD per 1M tokens)
# params_b: model size in billions, for no-KV-cache FLOPs
# ---------------------------------------------------------------------------

CLOUD_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-5.3": {
        "input_per_1m": 2.00,
        "output_per_1m": 10.00,
        "label": "GPT-5.3",
        "provider": "OpenAI",
        "params_b": 200.0,
        "energy_wh_per_1k_tokens": 0.4,
        "flops_per_token": 3.0e12,
    },
    "claude-opus-4.6": {
        "input_per_1m": 5.00,
        "output_per_1m": 25.00,
        "label": "Claude Opus 4.6",
        "provider": "Anthropic",
        "params_b": 137.0,
        "energy_wh_per_1k_tokens": 0.5,
        "flops_per_token": 4.0e12,
    },
    "gemini-3.1-pro": {
        "input_per_1m": 2.00,
        "output_per_1m": 12.00,
        "label": "Gemini 3.1 Pro",
        "provider": "Google",
        "params_b": 137.0,
        "energy_wh_per_1k_tokens": 0.35,
        "flops_per_token": 2.5e12,
    },
}


@dataclass(slots=True)
class ProviderSavings:
    """Savings compared to a single cloud provider."""

    provider: str = ""
    label: str = ""
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    energy_wh: float = 0.0
    energy_joules: float = 0.0
    flops: float = 0.0


@dataclass(slots=True)
class SavingsSummary:
    """Overall savings summary across all cloud providers."""

    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    local_cost: float = 0.0  # always 0 for local inference
    per_provider: List[ProviderSavings] = field(default_factory=list)
    monthly_projection: Dict[str, float] = field(default_factory=dict)
    session_start_ts: float = 0.0
    session_duration_hours: float = 0.0
    avg_cost_per_query: Dict[str, float] = field(default_factory=dict)
    cloud_agent_equivalent: Dict[str, int] = field(default_factory=dict)
    token_counting_version: int = TOKEN_COUNTING_VERSION


def compute_savings(
    prompt_tokens: int,
    completion_tokens: int,
    total_calls: int = 0,
    session_start: float = 0.0,
    prompt_tokens_evaluated: int = 0,
) -> SavingsSummary:
    """Compute savings vs cloud providers given token counts.

    Two token counts are used:

    - ``prompt_tokens`` — full prompt size (system prompt + all history).
      Used for **dollar cost** comparison since cloud providers bill for
      every input token on every request.
    - ``prompt_tokens_evaluated`` — actual tokens processed (KV-cache-
      aware).  In multi-turn conversations, subsequent turns only
      evaluate new tokens; the system prompt and prior context are
      served from KV cache.  Used for **FLOPs** and **energy**
      calculations since these reflect actual compute.

    If ``prompt_tokens_evaluated`` is 0 (e.g. old telemetry without the
    column), it falls back to ``prompt_tokens``.
    """
    if prompt_tokens_evaluated <= 0:
        prompt_tokens_evaluated = prompt_tokens
    total_tokens = prompt_tokens + completion_tokens
    total_tokens_evaluated = prompt_tokens_evaluated + completion_tokens
    providers: List[ProviderSavings] = []

    now = time.time()
    session_duration_hours = (now - session_start) / 3600 if session_start > 0 else 0.0

    monthly_projection: Dict[str, float] = {}
    avg_cost_per_query: Dict[str, float] = {}

    for key, pricing in CLOUD_PRICING.items():
        input_cost = (prompt_tokens / 1_000_000) * pricing["input_per_1m"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output_per_1m"]
        total_cost = input_cost + output_cost

        # KV-cache-aware FLOPs: 2 * P * T_evaluated
        # Only the actually-evaluated tokens require compute; cached
        # tokens from prior turns are served from KV cache.
        params_b = pricing.get("params_b", 200.0)
        params = params_b * 1e9
        flops = (
            2.0 * params * total_tokens_evaluated if total_tokens_evaluated > 0 else 0.0
        )
        # Derive Wh-per-FLOP from the provider's per-token constants:
        #   energy_wh_per_1k_tokens / (1000 * flops_per_token) = Wh per FLOP
        wh_per_flop = pricing["energy_wh_per_1k_tokens"] / (
            1000 * pricing.get("flops_per_token", 3e12)
        )
        energy_wh = flops * wh_per_flop

        providers.append(
            ProviderSavings(
                provider=key,
                label=pricing["label"],
                input_cost=input_cost,
                output_cost=output_cost,
                total_cost=total_cost,
                energy_wh=energy_wh,
                energy_joules=energy_wh * 3600,  # 1 Wh = 3600 J
                flops=flops,
            )
        )

        # Monthly projection: extrapolate current spend to 720 hours/month
        if session_duration_hours > 0:
            monthly_projection[key] = (total_cost / session_duration_hours) * 720
        else:
            monthly_projection[key] = 0.0

        # Average cost per query
        if total_calls > 0:
            avg_cost_per_query[key] = total_cost / total_calls
        else:
            avg_cost_per_query[key] = 0.0

    return SavingsSummary(
        total_calls=total_calls,
        total_prompt_tokens=prompt_tokens,
        total_completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        local_cost=0.0,
        per_provider=providers,
        monthly_projection=monthly_projection,
        session_start_ts=session_start,
        session_duration_hours=session_duration_hours,
        avg_cost_per_query=avg_cost_per_query,
        cloud_agent_equivalent={
            "moderate_low": 15,
            "moderate_high": 60,
            "heavy_low": 100,
            "heavy_high": 400,
        },
    )


def savings_to_dict(summary: SavingsSummary) -> Dict[str, Any]:
    """Convert SavingsSummary to a JSON-serializable dict."""
    return asdict(summary)


__all__ = [
    "CLOUD_PRICING",
    "ProviderSavings",
    "SavingsSummary",
    "compute_savings",
    "savings_to_dict",
]
