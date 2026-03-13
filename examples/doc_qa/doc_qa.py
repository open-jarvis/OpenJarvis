#!/usr/bin/env python3
"""Document QA — index documents and answer questions with citations.

Usage:
    python examples/doc_qa/doc_qa.py --help
    python examples/doc_qa/doc_qa.py --docs-path ./docs \
        --query "How does authentication work?"
    python examples/doc_qa/doc_qa.py --docs-path ./papers \
        --query "What are the main findings?" \
        --model gpt-4o --engine cloud
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Index documents and answer questions "
            "with memory-augmented citations."
        ),
    )
    parser.add_argument(
        "--docs-path",
        type=str,
        required=True,
        help="Path to the documents directory (or single file) to index.",
    )
    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="The question to answer based on the indexed documents.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen3:8b",
        help="Model to use for answering (default: qwen3:8b).",
    )
    parser.add_argument(
        "--engine",
        type=str,
        default="ollama",
        help="Engine backend: ollama, cloud, vllm, etc. (default: ollama).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="Chunk size for document indexing (default: 512).",
    )
    args = parser.parse_args()

    try:
        from openjarvis import Jarvis
    except ImportError:
        print(
            "Error: openjarvis is not installed. "
            "Install it with:  uv sync --extra dev",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Documents: {args.docs_path}")
    print(f"Query: {args.query}")
    print(f"Model: {args.model}  |  Engine: {args.engine}")
    print("-" * 60)

    try:
        j = Jarvis(model=args.model, engine_key=args.engine)
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

    # Step 1: Index documents into memory
    print("Indexing documents...")
    try:
        result = j.memory.index(args.docs_path, chunk_size=args.chunk_size)
        print(f"  Indexed {result['chunks']} chunks from {result['path']}")
    except Exception as exc:
        print(f"Error indexing documents: {exc}", file=sys.stderr)
        j.close()
        sys.exit(1)

    # Step 2: Ask the question with memory context enabled
    print("Searching for relevant context...")
    try:
        response = j.ask(
            args.query,
            context=True,
        )
    except Exception as exc:
        print(f"Error during QA: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        j.close()

    print()
    print("=" * 60)
    print("  Answer")
    print("=" * 60)
    print()
    print(response)
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
