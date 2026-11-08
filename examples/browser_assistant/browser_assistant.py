#!/usr/bin/env python3
"""Browser Assistant — web browsing agent with orchestrator loop.

Usage:
    python examples/browser_assistant/browser_assistant.py --help
    python examples/browser_assistant/browser_assistant.py \
        --query "Find the latest Python 3.13 features"
    python examples/browser_assistant/browser_assistant.py \
        --query "Compare pricing of AWS vs GCP" \
        --model gpt-4o --engine cloud
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Web browsing agent that searches, navigates, "
            "and synthesizes information from the web."
        ),
    )
    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="The question or task to research on the web.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen3:8b",
        help="Model to use for the agent (default: qwen3:8b).",
    )
    parser.add_argument(
        "--engine",
        type=str,
        default="ollama",
        help="Engine backend: ollama, cloud, vllm, etc. (default: ollama).",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=15,
        help="Maximum agent loop iterations (default: 15).",
    )
    args = parser.parse_args()

    try:
        from friday_ai import Friday
    except ImportError:
        print(
            "Error: friday_ai is not installed. "
            "Install it with:  uv sync --extra dev",
            file=sys.stderr,
        )
        sys.exit(1)

    tools = ["browser", "web_search", "think"]

    prompt = (
        "You are a web browsing assistant. Use browser and web_search tools to "
        "find accurate, up-to-date information.\n\n"
        "Steps:\n"
        "1. Use web_search to find relevant pages for the query.\n"
        "2. Use browser to visit the most promising results and extract details.\n"
        "3. Use think to reason about what you've found and identify gaps.\n"
        "4. Repeat until you have a comprehensive answer.\n\n"
        "Produce a well-structured answer with sources cited.\n\n"
        f"Query: {args.query}"
    )

    print(f"Query: {args.query}")
    print(
        f"Model: {args.model}  |  Engine: {args.engine}"
        f"  |  Max turns: {args.max_turns}"
    )
    print("-" * 60)

    try:
        j = Friday(model=args.model, engine_key=args.engine)
    except Exception as exc:
        print(
            f"Error: could not initialize Friday -- {exc}\n\n"
            "Make sure your engine is running. For Ollama:\n"
            "  ollama serve\n"
            "  ollama pull qwen3:8b\n\n"
            "For cloud engines, ensure API keys are set in your .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        result = j.ask_full(
            prompt,
            agent="orchestrator",
            tools=tools,
        )
        response = result["content"]
    except Exception as exc:
        print(f"Error during browsing: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        j.close()

    print(response)


if __name__ == "__main__":
    main()
