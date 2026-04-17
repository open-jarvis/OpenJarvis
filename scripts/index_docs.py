#!/usr/bin/env python3
"""Index OpenJarvis docs (README.md + docs/**/*.md) into a DenseMemory backend.

Usage:
    python scripts/index_docs.py              # print retrieval smoke test
    python scripts/index_docs.py --query "can i run this on cpu?"

This script is idempotent: it builds a fresh in-memory index each run.
There is no disk persistence by design — dense vectors are cheap to
rebuild and the docs corpus is small.

Embedding model: ``nomic-embed-text`` via Ollama. Pull it with
``ollama pull nomic-embed-text`` if you don't have it. Expected
indexing time for the full corpus: ~30s on a warm Ollama server.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from openjarvis.tools.storage.dense import (
    DenseMemory,
    MdChunk,
    chunk_markdown,
    dedupe_chunks,
)


def discover_md_files(repo_root: Path) -> list[Path]:
    """README + every markdown file under docs/. Sorted for determinism."""
    files: list[Path] = []
    readme = repo_root / "README.md"
    if readme.exists():
        files.append(readme)
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        files.extend(sorted(docs_dir.rglob("*.md")))
    return files


def build_index(
    repo_root: Path,
    *,
    max_section_tokens: int = 1000,
    paragraph_overlap_tokens: int = 100,
    dedupe: bool = True,
    # Empirical: on the actual OpenJarvis docs the boilerplate that
    # crowds retrieval ("OpenJarvis runs entirely on your hardware...")
    # appears in exactly 2 files (downloads.md ↔ installation.md).
    # Spec'd 3+ removes 0 chunks; 2+ removes 15 (1.3%) — all genuine
    # cross-file boilerplate. See the dry-run audit logged at index time.
    dedupe_min_files: int = 2,
    dedupe_threshold: float = 0.7,
) -> DenseMemory:
    """Chunk all markdown under *repo_root* and build a DenseMemory index.

    When ``dedupe`` is True (default), runs cross-file boilerplate
    deduplication after chunking and before embedding. The dedupe
    report is printed to stderr so reviewers can spot over-aggressive
    drops; if it removes >20% of the corpus a warning is emitted.
    """
    backend = DenseMemory()
    md_files = discover_md_files(repo_root)
    if not md_files:
        raise RuntimeError(f"No markdown files found under {repo_root}")

    all_chunks: list[MdChunk] = []
    for fpath in md_files:
        try:
            text = fpath.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"  WARN: could not read {fpath}: {exc}", file=sys.stderr)
            continue
        rel = str(fpath.relative_to(repo_root))
        all_chunks.extend(
            chunk_markdown(
                text,
                source=rel,
                max_section_tokens=max_section_tokens,
                paragraph_overlap_tokens=paragraph_overlap_tokens,
            )
        )

    print(
        f"Chunked {len(md_files)} files into {len(all_chunks)} chunks",
        file=sys.stderr,
    )

    if dedupe:
        before = len(all_chunks)
        all_chunks, report = dedupe_chunks(
            all_chunks,
            similarity_threshold=dedupe_threshold,
            min_files_for_dup=dedupe_min_files,
        )
        pct = report.removed_fraction * 100
        print(
            f"Dedupe: {before} -> {len(all_chunks)} chunks "
            f"({report.removed_count} removed, {pct:.1f}%) "
            f"across {len(report.groups)} clusters",
            file=sys.stderr,
        )
        for g in report.groups:
            dropped = sorted(set(g.dropped_sources))
            print(
                f"  KEPT  {g.kept_source}\n"
                f"  DROP  {len(g.dropped_indices)} from {dropped}\n"
                f"  TEXT  {g.sample_text!r}",
                file=sys.stderr,
            )
        if report.removed_fraction > 0.20:
            print(
                f"  WARNING: dedupe removed {pct:.1f}% of chunks (>20% threshold). "
                f"Review the list above before trusting the index.",
                file=sys.stderr,
            )

    print(
        f"Embedding {len(all_chunks)} chunks via nomic-embed-text...",
        file=sys.stderr,
    )
    t0 = time.time()
    backend.store_many(
        [c.content for c in all_chunks],
        sources=[c.source for c in all_chunks],
        metadatas=[{"breadcrumb": c.breadcrumb} for c in all_chunks],
    )
    print(
        f"Indexed {backend.count()} chunks in {time.time() - t0:.1f}s",
        file=sys.stderr,
    )
    return backend


def _print_hits(query: str, backend: DenseMemory, top_k: int = 3) -> None:
    print(f"\nQ: {query}")
    print("-" * 80)
    hits = backend.retrieve(query, top_k=top_k)
    if not hits:
        print("  (no hits)")
        return
    for i, h in enumerate(hits, 1):
        preview = h.content.replace("\n", " ")[:200]
        print(f"  [{i}] score={h.score:.3f}  src={h.source}")
        print(f"      breadcrumb={h.metadata.get('breadcrumb', '')}")
        print(f"      {preview}{'...' if len(h.content) > 200 else ''}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (default: script's parent)",
    )
    p.add_argument(
        "--query",
        "-q",
        action="append",
        default=None,
        help="Query to test against the built index (can be given multiple times)",
    )
    p.add_argument("--top-k", type=int, default=3, help="Top-K results per query")
    args = p.parse_args()

    repo_root = Path(args.repo_root).resolve()
    backend = build_index(repo_root)

    queries = args.query or [
        "can I run the orchestrator agent on a laptop without a gpu?",
        "what inference engines does openjarvis support?",
        "how do I add a new channel integration?",
        "why would I choose the dense memory backend over sqlite?",
    ]
    for q in queries:
        _print_hits(q, backend, top_k=args.top_k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
