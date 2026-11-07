"""Cost computation for agentic eval runs — wraps engine/cloud.py pricing."""

from __future__ import annotations

from friday_ai.engine.cloud import PRICING, estimate_cost


def compute_turn_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost for a single agent turn.

    Delegates to the canonical ``estimate_cost()`` from ``engine/cloud.py``.
    Returns 0.0 for models not in the pricing table (e.g. local models).
    """
    return estimate_cost(model, input_tokens, output_tokens)


__all__ = ["PRICING", "compute_turn_cost", "estimate_cost"]
