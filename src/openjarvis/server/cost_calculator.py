"""Cost calculator -- estimate monthly cloud API costs for common use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from openjarvis.server.savings import CLOUD_PRICING


@dataclass(slots=True)
class CostEstimate:
    """Estimated cost for a provider given a usage scenario."""

    provider: str
    label: str
    monthly_cost: float
    annual_cost: float
    input_cost: float
    output_cost: float
    total_calls_per_month: int


@dataclass(slots=True)
class Scenario:
    """A prebuilt usage scenario."""

    name: str
    label: str
    description: str
    calls_per_month: int
    avg_input_tokens: int
    avg_output_tokens: int


SCENARIOS: Dict[str, Scenario] = {
    "daily_briefing": Scenario(
        name="daily_briefing",
        label="Daily Briefing",
        description="Morning brief every 5 minutes, 24/7",
        calls_per_month=8_640,
        avg_input_tokens=500,
        avg_output_tokens=200,
    ),
    "email_triage": Scenario(
        name="email_triage",
        label="Email Triage",
        description="Email classification and drafting every 5 minutes",
        calls_per_month=8_640,
        avg_input_tokens=800,
        avg_output_tokens=300,
    ),
    "research_assistant": Scenario(
        name="research_assistant",
        label="Research Assistant",
        description="Deep research queries, ~20 per day",
        calls_per_month=600,
        avg_input_tokens=2_000,
        avg_output_tokens=1_500,
    ),
    "overnight_coder": Scenario(
        name="overnight_coder",
        label="Overnight Coder",
        description="Automated coding tasks, ~100 per night",
        calls_per_month=3_000,
        avg_input_tokens=3_000,
        avg_output_tokens=2_000,
    ),
    "always_on": Scenario(
        name="always_on",
        label="Always-On (All Above)",
        description="All use cases combined",
        calls_per_month=20_880,
        avg_input_tokens=1_200,
        avg_output_tokens=700,
    ),
}


def estimate_monthly_cost(
    calls_per_month: int,
    avg_input_tokens: int,
    avg_output_tokens: int,
    provider_key: str,
) -> CostEstimate:
    """Estimate monthly cost for a provider given usage parameters."""
    pricing = CLOUD_PRICING.get(provider_key)
    if pricing is None:
        raise ValueError(f"Unknown provider: {provider_key}")

    total_input = calls_per_month * avg_input_tokens
    total_output = calls_per_month * avg_output_tokens

    input_cost = (total_input / 1_000_000) * pricing["input_per_1m"]
    output_cost = (total_output / 1_000_000) * pricing["output_per_1m"]
    monthly = input_cost + output_cost

    return CostEstimate(
        provider=provider_key,
        label=str(pricing["label"]),
        monthly_cost=monthly,
        annual_cost=monthly * 12,
        input_cost=input_cost,
        output_cost=output_cost,
        total_calls_per_month=calls_per_month,
    )


def estimate_scenario(scenario_name: str) -> List[CostEstimate]:
    """Estimate costs for all providers for a named scenario."""
    scenario = SCENARIOS.get(scenario_name)
    if scenario is None:
        raise ValueError(f"Unknown scenario: {scenario_name}")
    return [
        estimate_monthly_cost(
            scenario.calls_per_month,
            scenario.avg_input_tokens,
            scenario.avg_output_tokens,
            provider_key,
        )
        for provider_key in CLOUD_PRICING
    ]


def estimate_all_scenarios() -> Dict[str, List[CostEstimate]]:
    """Estimate costs for all scenarios and all providers."""
    return {name: estimate_scenario(name) for name in SCENARIOS}


__all__ = [
    "SCENARIOS",
    "CostEstimate",
    "Scenario",
    "estimate_all_scenarios",
    "estimate_monthly_cost",
    "estimate_scenario",
]
