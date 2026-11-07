#!/usr/bin/env python3
"""Test Generator — generate comprehensive tests for a Python module with a ReAct agent.

Usage::

    python examples/code_companion/test_gen.py \
        --module src/friday_ai/tools/calculator.py
    python examples/code_companion/test_gen.py \
        --module src/app/utils.py --framework unittest
    python examples/code_companion/test_gen.py \
        --module src/app/utils.py --output tests/test_utils.py
"""

from __future__ import annotations

import os
import sys

import click


@click.command()
@click.option(
    "--module",
    required=True,
    type=click.Path(exists=True),
    help="Path to the Python module to generate tests for.",
)
@click.option(
    "--framework",
    default="pytest",
    show_default=True,
    type=click.Choice(["pytest", "unittest"], case_sensitive=False),
    help="Test framework to target.",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(),
    help=(
        "File path to save generated tests. "
        "Defaults to test_<module_name>.py in the current directory."
    ),
)
@click.option(
    "--model",
    default="qwen3:8b",
    show_default=True,
    help="Model to use for test generation.",
)
@click.option(
    "--engine",
    "engine_key",
    default="ollama",
    show_default=True,
    help="Engine backend (ollama, cloud, vllm, etc.).",
)
def main(
    module: str,
    framework: str,
    output: str | None,
    model: str,
    engine_key: str,
) -> None:
    """Generate comprehensive tests for a Python MODULE using a ReAct agent.

    The agent reads the module source, reasons about edge cases and behavior,
    and produces a complete test file. Tests are saved to a file or printed
    to stdout.
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

    tools = ["file_read", "think", "file_write"]

    # Derive default output path from the module name.
    module_basename = os.path.basename(module).removesuffix(".py")
    if output is None:
        output = f"test_{module_basename}.py"

    prompt = (
        f"You are an expert Python test engineer. Generate comprehensive "
        f"tests for the module at '{module}' using the **{framework}** "
        f"framework.\n\n"
        "Steps:\n"
        f"1. Use file_read to read the source code of '{module}'.\n"
        "2. Use think to plan test cases: happy paths, edge cases, error "
        "handling, and boundary conditions.\n"
        "3. Read any related modules or base classes if needed for context.\n"
        f"4. Use file_write to save the generated tests to '{output}'.\n\n"
        "Guidelines:\n"
        "- Each public function/method should have at least one test.\n"
        "- Include docstrings on each test explaining what it verifies.\n"
        "- Test edge cases (empty input, None, large values, invalid types).\n"
        "- Use mocks/patches for external dependencies.\n"
        "- The test file must be self-contained and runnable.\n"
    )

    click.echo(f"Generating tests for: {module}")
    click.echo(f"Framework: {framework}  |  Output: {output}")
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
        click.echo(f"Error during test generation: {exc}", err=True)
        sys.exit(1)
    finally:
        j.close()

    click.echo(response)
    click.echo(f"\nTests saved to: {output}")


if __name__ == "__main__":
    main()
