"""Savings calculation — compare local inference cost against cloud providers.

FLOPs and energy use a no-KV-cache model: P * N * (N+1) where P = params,
N = total tokens. This reflects full recompute without cached attention.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

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


def compute_savings(
    prompt_tokens: int,
    completion_tokens: int,
    total_calls: int = 0,
    session_start: float = 0.0,
) -> SavingsSummary:
    """Compute savings vs cloud providers given token counts."""
    total_tokens = prompt_tokens + completion_tokens
    providers: List[ProviderSavings] = []

    now = time.time()
    session_duration_hours = (now - session_start) / 3600 if session_start > 0 else 0.0

    monthly_projection: Dict[str, float] = {}
    avg_cost_per_query: Dict[str, float] = {}

    for key, pricing in CLOUD_PRICING.items():
        input_cost = (prompt_tokens / 1_000_000) * pricing["input_per_1m"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output_per_1m"]
        total_cost = input_cost + output_cost

        # No-KV-cache FLOPs: P * N * (N+1)
        params_b = pricing.get("params_b", 200.0)
        params = params_b * 1e9
        flops = (
            params * total_tokens * (total_tokens + 1)
            if total_tokens > 0 else 0.0
        )
        # Scale energy by same ratio as FLOPs (energy ∝ compute)
        flops_with_cache = (
            total_tokens * pricing.get("flops_per_token", 3e12)
            if total_tokens > 0 else 0.0
        )
        scale = (flops / flops_with_cache) if flops_with_cache > 0 else 1.0
        energy_wh = (
            (total_tokens / 1000) * pricing["energy_wh_per_1k_tokens"] * scale
        )

        providers.append(ProviderSavings(
            provider=key,
            label=pricing["label"],
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
            energy_wh=energy_wh,
            energy_joules=energy_wh * 3600,  # 1 Wh = 3600 J
            flops=flops,
        ))

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
