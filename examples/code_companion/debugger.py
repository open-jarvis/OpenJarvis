#!/usr/bin/env python3
"""Debug Assistant — investigate errors and propose fixes with a ReAct agent.

Usage::

    python examples/code_companion/debugger.py \
        --error "TypeError: NoneType has no attribute 'split'"
    python examples/code_companion/debugger.py \
        --error "KeyError: 'user_id'" --file src/app/views.py
    python examples/code_companion/debugger.py \
        --error "Segfault in libfoo.so" --model gpt-4o
"""

from __future__ import annotations

import sys

import click


@click.command()
@click.option(
    "--error",
    required=True,
    help="Error message or stack trace to investigate.",
)
@click.option(
    "--file",
    "file_path",
    default=None,
    type=click.Path(),
    help="Optional file path where the error occurred.",
)
@click.option(
    "--model",
    default="qwen3:8b",
    show_default=True,
    help="Model to use for debugging.",
)
@click.option(
    "--engine",
    "engine_key",
    default="ollama",
    show_default=True,
    help="Engine backend (ollama, cloud, vllm, etc.).",
)
def main(
    error: str,
    file_path: str | None,
    model: str,
    engine_key: str,
) -> None:
    """Investigate an error and propose a fix using a ReAct agent.

    The agent reads relevant source files, runs diagnostic commands,
    reasons about root causes, and suggests a concrete fix.
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

    tools = ["file_read", "shell_exec", "think"]

    file_context = ""
    if file_path:
        file_context = f"\nThe error occurred in the file: {file_path}\n"

    prompt = (
        "You are an expert debugger. Investigate the following error and "
        "propose a fix.\n\n"
        f"**Error:**\n```\n{error}\n```\n"
        f"{file_context}\n"
        "Steps:\n"
        "1. If a file path is given, use file_read to examine the source.\n"
        "2. Use shell_exec to run diagnostic commands (e.g., grep for the "
        "symbol, check imports, list directory contents) as needed.\n"
        "3. Use think to reason about root causes.\n"
        "4. Read any additional files that may be related.\n\n"
        "Produce a structured response with these sections:\n"
        "- **Root Cause**: explanation of why the error occurs.\n"
        "- **Proposed Fix**: concrete code change or configuration fix.\n"
        "- **Prevention**: how to prevent similar issues in the future "
        "(e.g., type hints, validation, tests)."
    )

    click.echo(f"Investigating error: {error}")
    if file_path:
        click.echo(f"File: {file_path}")
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
        click.echo(f"Error during debugging: {exc}", err=True)
        sys.exit(1)
    finally:
        j.close()

    click.echo(response)


if __name__ == "__main__":
    main()
