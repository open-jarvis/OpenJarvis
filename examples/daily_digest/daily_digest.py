#!/usr/bin/env python3
"""Daily Digest — morning briefing operator that searches and summarizes news.

Usage:
    python examples/daily_digest/daily_digest.py --help
    python examples/daily_digest/daily_digest.py --topics "AI,robotics,space"
    python examples/daily_digest/daily_digest.py --topics "finance,crypto" \
        --model gpt-4o --engine cloud
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a morning news briefing for chosen topics.",
    )
    parser.add_argument(
        "--topics",
        type=str,
        default="AI,tech",
        help=(
            "Comma-separated list of topics to include "
            "in the digest (default: AI,tech)."
        ),
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen3:8b",
        help="Model to use for generation (default: qwen3:8b).",
    )
    parser.add_argument(
        "--engine",
        type=str,
        default="ollama",
        help="Engine backend: ollama, cloud, vllm, etc. (default: ollama).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional file path to save the digest.",
    )
    args = parser.parse_args()

    topic_list = [t.strip() for t in args.topics.split(",") if t.strip()]
    if not topic_list:
        print("Error: --topics must contain at least one topic.", file=sys.stderr)
        sys.exit(1)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        from friday_ai import Friday
    except ImportError:
        print(
            "Error: friday_ai is not installed. "
            "Install it with:  uv sync --extra dev",
            file=sys.stderr,
        )
        sys.exit(1)

    tools = ["web_search", "think"]

    prompt = (
        f"Today is {today}. You are a morning briefing assistant.\n\n"
        "Search for and summarize the top news stories on the following topics: "
        f"{', '.join(topic_list)}.\n\n"
        "For each topic, provide 3-5 bullet points covering the most important "
        "developments. End with a one-paragraph outlook for the day.\n\n"
        "Use web_search to find current information and think to organize "
        "your findings before writing the digest."
    )

    print(f"{'=' * 60}")
    print(f"  Daily Digest -- {today}")
    print(f"  Topics: {', '.join(topic_list)}")
    print(f"{'=' * 60}")
    print()

    try:
        j = Friday(model=args.model, engine_key=args.engine)
    except Exception as exc:
        print(
            f"Error: could not initialize Friday -- {exc}\n\n"
            "Make sure an inference engine is running (e.g., ollama serve) "
            "and the friday_ai package is installed (uv sync).",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        response = j.ask(
            prompt,
            agent="orchestrator",
            tools=tools,
        )
    except Exception as exc:
        print(f"Error during generation: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        j.close()

    print(response)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(response)
        print(f"\nDigest saved to {args.output}")

    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
