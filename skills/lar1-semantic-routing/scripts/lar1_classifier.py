#!/usr/bin/env python3
"""LAR-1 Semantic Routing Classifier for OpenJarvis.

Routes queries to the cheapest capable model based on 5 semantic dimensions:
L (Likelihood), C (Cognition), E (Evidence), T (Time), S (Space).

Usage:
    from lar1_classifier import classify, RoutingDecision

    meta = {"T": "recall", "C": "inf", "E": "derived:log", "L": 0.65}
    decision = classify(meta)
    print(decision.route)   # "cloud"
    print(decision.model)   # "gpt-4o-mini"
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_THRESHOLDS = {
    "low": 0.3,
    "medium": 0.5,
    "high": 0.7,
}
DEFAULT_MODELS = {
    "local_fast": "qwen2.5-7b",
    "local_medium": "llama3.1-8b",
    "cloud_fast": "gpt-4o-mini",
    "cloud_medium": "gpt-4o",
    "cloud_premium": "gpt-4o",
}


@dataclass
class RoutingDecision:
    """Result of a LAR-1 routing decision."""
    route: str  # "local", "cloud", or "hybrid"
    model_tier: str  # "fast", "medium", "premium"
    model_name: str
    reasons: list[str] = field(default_factory=list)


def classify(
    metadata: dict,
    thresholds: Optional[dict] = None,
    models: Optional[dict] = None,
) -> RoutingDecision:
    """Classify a query using LAR-1 metadata and return routing decision.

    Rules evaluated in priority order (first match wins):

    1. L < low_threshold → cloud premium (low confidence)
    2. C=unc → cloud premium (uncertainty)
    3. E=speculative → cloud fast (speculative reasoning)
    4. T=recall → cloud (memory retrieval)
    5. C=exp → cloud fast (exploration)
    6. L >= high_threshold AND C in (obs, dec, meta) → local fast
    7. C=meta → local (meta-conversation)
    8. default → local fast

    Args:
        metadata: LAR-1 metadata dict with keys T, C, E, L (and optional S).
        thresholds: Override default threshold values.
        models: Override default model names.

    Returns:
        RoutingDecision with route, model_tier, model_name, and reasons.
    """
    th = thresholds or DEFAULT_THRESHOLDS
    mod = models or DEFAULT_MODELS

    L = metadata.get("L")
    C = metadata.get("C", "").lower()
    E = metadata.get("E", "").lower()
    T = metadata.get("T", "").lower()
    S = metadata.get("S", "").lower()

    # Rule 1: Low confidence → cloud premium
    if L is not None and L < th["low"]:
        return RoutingDecision(
            route="cloud",
            model_tier="premium",
            model_name=mod["cloud_premium"],
            reasons=[f"low confidence ({L} < {th['low']}) → cloud premium"],
        )

    # Rule 2: Uncertain cognition → cloud premium
    if C == "unc":
        return RoutingDecision(
            route="cloud",
            model_tier="premium",
            model_name=mod["cloud_premium"],
            reasons=[f"exploratory/uncertain stance (unc) → cloud premium"],
        )

    # Rule 3: Speculative evidence → cloud fast
    if E == "speculative":
        return RoutingDecision(
            route="cloud",
            model_tier="fast",
            model_name=mod["cloud_fast"],
            reasons=[f"speculative evidence → cloud"],
        )

    # Rule 4: Memory recall → cloud medium
    if T.startswith("recall"):
        return RoutingDecision(
            route="cloud",
            model_tier="medium",
            model_name=mod["cloud_medium"],
            reasons=[f"memory retrieval (T={T}) → cloud"],
        )

    # Rule 5: Exploration → cloud fast
    if C == "exp":
        return RoutingDecision(
            route="cloud",
            model_tier="fast",
            model_name=mod["cloud_fast"],
            reasons=[f"exploratory stance (exp) → cloud"],
        )

    # Rule 6: High confidence + factual/decisive → local fast
    if L is not None and L >= th["high"] and C in ("obs", "dec", "meta"):
        return RoutingDecision(
            route="local",
            model_tier="fast",
            model_name=mod["local_fast"],
            reasons=[f"high confidence ({L} ≥ {th['high']}) + {C} → fast local"],
        )

    # Rule 7: Meta conversation → local
    if C == "meta":
        return RoutingDecision(
            route="local",
            model_tier="fast",
            model_name=mod["local_fast"],
            reasons=[f"meta-conversation → local"],
        )

    # Default: local fast
    return RoutingDecision(
        route="local",
        model_tier="fast",
        model_name=mod["local_fast"],
        reasons=[f"default → local fast"],
    )


def cli():
    """Command-line interface for LAR-1 routing."""
    import argparse

    parser = argparse.ArgumentParser(description="LAR-1 Semantic Routing Classifier")
    parser.add_argument("--metadata", "-m", type=str, required=True,
                        help='JSON metadata string, e.g. \'{"T":"now","C":"obs","L":0.99}\'')
    args = parser.parse_args()

    metadata = json.loads(args.metadata)
    decision = classify(metadata)
    print(json.dumps({
        "route": decision.route,
        "model_tier": decision.model_tier,
        "model_name": decision.model_name,
        "reasons": decision.reasons,
    }, indent=2))


if __name__ == "__main__":
    cli()
