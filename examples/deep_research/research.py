#!/usr/bin/env python3
"""Deep Research Assistant — multi-source research with memory-augmented orchestrator.

Usage:
    python examples/deep_research/research.py "quantum computing advances"
    python examples/deep_research/research.py "climate policy" \
        --model gpt-4o --engine cloud
    python examples/deep_research/research.py "rust vs go" \
        --output report.md
"""

from __future__ import annotations

import sys

import click


@click.command()
@click.argument("topic")
@click.option(
    "--model",
    default="qwen3:8b",
    show_default=True,
    help="Model to use for research.",
)
@click.option(
    "--engine",
    "engine_key",
    default="ollama",
    show_default=True,
    help="Engine backend (ollama, cloud, vllm, etc.).",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(),
    help="Optional file path to save the research report.",
)
def main(
    topic: str,
    model: str,
    engine_key: str,
    output: str | None,
) -> None:
    """Run a deep research session on TOPIC using an orchestrator agent.

    The agent searches the web, stores findings in memory, cross-references
    sources, and produces a comprehensive report with citations.
    """
    # Lazy import so that --help works without a running engine or heavy deps.
    try:
        from openjarvis import Jarvis
    except ImportError:
        click.echo(
            "Error: openjarvis is not installed. "
            "Install it with:  uv sync --extra dev",
            err=True,
        )
        sys.exit(1)

    tools = ["web_search", "think", "file_write", "memory_store", "memory_search"]

    system_prompt = (
        "You are a deep research assistant. When given a topic:\n"
        "1. Search the web for recent, authoritative sources\n"
        "2. Store key findings in memory for cross-referencing\n"
        "3. Synthesize a comprehensive report with citations\n"
        "4. Save the final report to a file\n\n"
        "Always cite your sources and distinguish between established facts "
        "and emerging claims."
    )

    click.echo(f"Researching: {topic}")
    click.echo(f"Model: {model}  |  Engine: {engine_key}")
    click.echo("-" * 60)

    try:
        j = Jarvis(model=model, engine_key=engine_key)
    except Exception as exc:
        click.echo(
            f"Error: could not initialize Jarvis — {exc}\n\n"
            "Make sure your engine is running. For Ollama:\n"
            "  ollama serve\n"
            "  ollama pull qwen3:8b\n\n"
            "For cloud engines, ensure API keys are set in your .env file.",
            err=True,
        )
        sys.exit(1)

    try:
        prompt = (
            f"{system_prompt}\n\n"
            "Research the following topic in depth "
            f"and produce a report:\n\n{topic}"
        )
        response = j.ask(
            prompt,
            agent="orchestrator",
            tools=tools,
            temperature=0.5,
        )
    except Exception as exc:
        click.echo(f"Error during research: {exc}", err=True)
        sys.exit(1)
    finally:
        j.close()

    click.echo(response)

    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(response)
        click.echo(f"\nReport saved to {output}")


if __name__ == "__main__":
    main()
