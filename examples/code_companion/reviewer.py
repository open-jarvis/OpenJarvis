#!/usr/bin/env python3
"""Code Review Assistant — review diffs between branches with a ReAct agent.

Usage:
    python examples/code_companion/reviewer.py
    python examples/code_companion/reviewer.py --branch feature-x --base main
    python examples/code_companion/reviewer.py --model gpt-4o --engine cloud
"""

from __future__ import annotations

import sys

import click


@click.command()
@click.option(
    "--branch",
    default="HEAD",
    show_default=True,
    help="Branch (or commit) to review.",
)
@click.option(
    "--base",
    default="main",
    show_default=True,
    help="Base branch to diff against.",
)
@click.option(
    "--model",
    default="qwen3:8b",
    show_default=True,
    help="Model to use for the review.",
)
@click.option(
    "--engine",
    "engine_key",
    default="ollama",
    show_default=True,
    help="Engine backend (ollama, cloud, vllm, etc.).",
)
def main(
    branch: str,
    base: str,
    model: str,
    engine_key: str,
) -> None:
    """Review code changes between BASE and BRANCH using a ReAct agent.

    The agent reads the git diff and log, inspects relevant source files,
    and produces structured feedback covering issues found, suggestions,
    and an overall assessment.
    """
    try:
        from friday_ai import Friday
    except ImportError:
        click.echo(
            "Error: friday_ai is not installed. "
            "Install it with:  uv sync --extra dev",
            err=True,
        )
        sys.exit(1)

    tools = ["git_diff", "git_log", "file_read", "think"]

    prompt = (
        f"You are an expert code reviewer. Review the changes between "
        f"the base branch '{base}' and the branch '{branch}'.\n\n"
        "Steps:\n"
        "1. Use git_diff to see what changed between the two refs.\n"
        "2. Use git_log to understand the commit history.\n"
        "3. Use file_read to inspect any files that need more context.\n"
        "4. Use think to reason about code quality, bugs, and design.\n\n"
        "Produce a structured review with these sections:\n"
        "- **Summary**: one-paragraph overview of the changes.\n"
        "- **Issues Found**: list of bugs, logic errors, or security concerns.\n"
        "- **Suggestions**: improvements for readability, performance, or style.\n"
        "- **Overall Assessment**: APPROVE, REQUEST CHANGES, or COMMENT, "
        "with a brief justification."
    )

    click.echo(f"Reviewing: {base}..{branch}")
    click.echo(f"Model: {model}  |  Engine: {engine_key}")
    click.echo("-" * 60)

    try:
        j = Friday(model=model, engine_key=engine_key)
    except Exception as exc:
        click.echo(
            f"Error: could not initialize Friday — {exc}\n\n"
            "Make sure your engine is running. For Ollama:\n"
            "  ollama serve\n"
            "  ollama pull qwen3:8b\n\n"
            "For cloud engines, ensure API keys are set in your .env file.",
            err=True,
        )
        sys.exit(1)

    try:
        response = j.ask(prompt, agent="native_react", tools=tools)
    except Exception as exc:
        click.echo(f"Error during review: {exc}", err=True)
        sys.exit(1)
    finally:
        j.close()

    click.echo(response)


if __name__ == "__main__":
    main()
