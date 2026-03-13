#!/usr/bin/env python3
"""Multi-Model Router — route queries to the cheapest capable model.

Usage:
    python examples/multi_model_router/multi_model_router.py --help
    python examples/multi_model_router/multi_model_router.py --query "What is 2+2?"
    python examples/multi_model_router/multi_model_router.py \
        --query "Explain quantum entanglement step by step"
    python examples/multi_model_router/multi_model_router.py \
        --query "def fibonacci(n):" --strategy bandit --engine cloud
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Route queries to the cheapest capable model "
            "using OpenJarvis learning/routing."
        ),
    )
    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="The query to route and answer.",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="heuristic",
        choices=["heuristic", "bandit"],
        help=(
            "Routing strategy: heuristic (rule-based) or "
            "bandit (Thompson Sampling). Default: heuristic."
        ),
    )
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Comma-separated list of model identifiers to route between. "
        "If not specified, uses all models available from the engine.",
    )
    parser.add_argument(
        "--engine",
        type=str,
        default="ollama",
        help="Engine backend: ollama, cloud, vllm, etc. (default: ollama).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show routing decision details.",
    )
    args = parser.parse_args()

    try:
        from openjarvis import Jarvis
        from openjarvis.learning.routing.router import (
            HeuristicRouter,
            build_routing_context,
        )
    except ImportError:
        print(
            "Error: openjarvis is not installed. "
            "Install it with:  uv sync --extra dev",
            file=sys.stderr,
        )
        sys.exit(1)

    # Initialize Jarvis to discover available models
    try:
        j = Jarvis(engine_key=args.engine)
    except Exception as exc:
        print(
            f"Error: could not initialize Jarvis -- {exc}\n\n"
            "Make sure your engine is running. For Ollama:\n"
            "  ollama serve\n"
            "  ollama pull qwen3:8b\n\n"
            "For cloud engines, ensure API keys are set in your .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Determine available models
    if args.models:
        available_models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        try:
            available_models = j.list_models()
        except Exception:
            available_models = []

    if not available_models:
        print(
            "Error: no models available. Provide --models or ensure the engine "
            "has models loaded.",
            file=sys.stderr,
        )
        j.close()
        sys.exit(1)

    # Build routing context from the query
    context = build_routing_context(args.query)

    # Select the model using the chosen strategy
    if args.strategy == "bandit":
        from openjarvis.learning.routing.learned_router import LearnedRouterPolicy

        router = LearnedRouterPolicy()
        selected_model = router.select_model(context)
    else:
        router = HeuristicRouter(available_models)
        selected_model = router.select_model(context)

    if args.verbose:
        print("Routing Decision")
        print("-" * 40)
        print(f"  Strategy:   {args.strategy}")
        print(f"  Available:  {', '.join(available_models)}")
        print(f"  Query len:  {context.query_length}")
        print(f"  Has code:   {context.has_code}")
        print(f"  Has math:   {context.has_math}")
        print(f"  Selected:   {selected_model}")
        print("-" * 40)
    else:
        print(f"Routed to: {selected_model}")

    print(f"Query: {args.query}")
    print("-" * 60)

    # Send the query to the selected model
    try:
        response = j.ask(args.query, model=selected_model)
    except Exception as exc:
        print(f"Error during inference: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        j.close()

    print(response)


if __name__ == "__main__":
    main()
