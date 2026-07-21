#!/usr/bin/env python3
"""Demo: LAR-1 Semantic Routing with OpenJarvis."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

try:
    from lar1_classifier import classify
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    from lar1_classifier import classify


def main():
    print("=== LAR-1 x OpenJarvis: Routing Demo ===
")

    scenarios = [
        ("Factual Q&A",      {"T": "now", "C": "obs", "E": "direct",         "L": 0.99}),
        ("Deep research",    {"T": "now", "C": "exp", "E": "speculative",    "L": 0.30}),
        ("Memory recall",    {"T": "recall:session_prev", "C": "inf", "E": "derived:log", "L": 0.65}),
        ("Decision + high",  {"T": "now", "C": "dec", "E": "direct:user_input", "L": 0.95}),
        ("Uncertain guess",  {"T": "now", "C": "unc", "E": "derived:guess",  "L": 0.40}),
        ("Meta conversation",{"T": "now", "C": "meta", "E": "direct",        "L": 0.80}),
        ("No metadata",      {}) ,
    ]

    for label, meta in scenarios:
        decision = classify(meta)
        print(f"  # {label}")
        print(f"     LAR-1:   T={meta.get('T','-')} C={meta.get('C','-')} "
              f"E={meta.get('E','-')} L={meta.get('L','-')}")
        print(f"     Route:   {decision.route}")
        print(f"     Model:   {decision.model_name} ({decision.model_tier})")
        print(f"     Why:     {'; '.join(decision.reasons)}")
        print()

    routes = {"local": 0, "cloud": 0, "hybrid": 0}
    for _, meta in scenarios:
        d = classify(meta)
        routes[d.route] += 1

    total = sum(routes.values())
    savings = (routes["local"] + routes["hybrid"]) / total * 100
    print(f"  -- Summary --")
    print(f"  Local:  {routes['local']}")
    print(f"  Cloud:  {routes['cloud']}")
    print(f"  Hybrid: {routes['hybrid']}")
    print(f"  Cost savings: ~{savings:.0f}% vs all-cloud routing")


if __name__ == "__main__":
    main()
