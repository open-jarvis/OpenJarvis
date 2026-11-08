#!/usr/bin/env python3
"""Security Scanner — scan a local project for secrets and vulnerabilities.

Usage:
    python examples/security_scanner/security_scanner.py --help
    python examples/security_scanner/security_scanner.py --path ./my_project
    python examples/security_scanner/security_scanner.py --path ./my_project \
        --model gpt-4o --engine cloud
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a local project directory for secrets, "
            "vulnerabilities, and security issues."
        ),
    )
    parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to the project directory to scan.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen3:8b",
        help="Model to use for analysis (default: qwen3:8b).",
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
        default=20,
        help="Maximum agent loop iterations (default: 20).",
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

    tools = ["shell_exec", "file_read", "code_interpreter", "think"]

    prompt = (
        "You are a security auditor. Scan the project directory and identify "
        "potential security issues.\n\n"
        "Steps:\n"
        "1. Use shell_exec to list files and understand the project structure.\n"
        "2. Use file_read to inspect configuration files, environment files, "
        "and source code for hardcoded secrets (API keys, passwords, tokens).\n"
        "3. Use shell_exec to search for common vulnerability patterns "
        "(e.g., SQL string concatenation, insecure deserialization).\n"
        "4. Use code_interpreter to analyze dependency files "
        "for known vulnerable packages.\n"
        "5. Use think to reason about the severity of each finding.\n\n"
        "Produce a structured security report with these sections:\n"
        "- **Secrets Found**: any hardcoded credentials, API keys, or tokens.\n"
        "- **Vulnerabilities**: code patterns that could be exploited.\n"
        "- **Dependency Issues**: outdated or vulnerable packages.\n"
        "- **Recommendations**: prioritized list of fixes.\n"
        "- **Risk Level**: CRITICAL, HIGH, MEDIUM, or LOW overall assessment.\n\n"
        f"Project path: {args.path}"
    )

    print(f"Scanning: {args.path}")
    print(f"Model: {args.model}  |  Engine: {args.engine}")
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
            agent="native_react",
            tools=tools,
        )
        response = result["content"]
    except Exception as exc:
        print(f"Error during scan: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        j.close()

    print(response)


if __name__ == "__main__":
    main()
