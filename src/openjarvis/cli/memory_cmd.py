"""``jarvis memory`` — memory management subcommands."""

from __future__ import annotations

import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import track
from rich.table import Table

from openjarvis.core.config import load_config
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage.chunking import ChunkConfig
from openjarvis.tools.storage.ingest import ingest_path


def _get_backend(backend_key: str | None = None):
    """Instantiate the configured (or overridden) memory backend."""
    config = load_config()
    key = backend_key or config.memory.default_backend

    # Ensure backends are registered
    import openjarvis.tools.storage  # noqa: F401

    if not MemoryRegistry.contains(key):
        raise click.ClickException(
            f"Memory backend '{key}' not found. "
            f"Available: {', '.join(MemoryRegistry.keys())}"
        )

    if key == "sqlite":
        return MemoryRegistry.create(key, db_path=config.memory.db_path)
    return MemoryRegistry.create(key)


@click.group()
def memory() -> None:
    """Manage the memory store."""


@memory.command()
@click.argument("path")
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
@click.option(
    "--chunk-size",
    default=512,
    type=int,
    help="Chunk size in tokens.",
)
@click.option(
    "--chunk-overlap",
    default=64,
    type=int,
    help="Overlap between chunks in tokens.",
)
def index(
    path: str,
    backend: str | None,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """Index documents from a file or directory."""
    console = Console(stderr=True)
    target = Path(path)

    if not target.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise SystemExit(1)

    t0 = time.time()
    cfg = ChunkConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    console.print(f"[cyan]Indexing[/cyan] {path} ...")
    chunks = ingest_path(target, config=cfg)

    if not chunks:
        console.print("[yellow]No indexable content found.[/yellow]")
        return

    mem = _get_backend(backend)
    try:
        for chunk in track(chunks, description="Storing chunks...", console=console):
            mem.store(
                chunk.content,
                source=chunk.source,
                metadata={
                    "offset": chunk.offset,
                    "index": chunk.index,
                },
            )
    finally:
        if hasattr(mem, "close"):
            mem.close()

    elapsed = time.time() - t0
    sources = {c.source for c in chunks}
    console.print(
        f"[green]Indexed {len(chunks)} chunks "
        f"from {len(sources)} file(s) "
        f"in {elapsed:.1f}s.[/green]"
    )


@memory.command()
@click.argument("query", nargs=-1, required=True)
@click.option(
    "--top-k",
    "-k",
    default=5,
    type=int,
    help="Number of results to return.",
)
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
def search(
    query: tuple[str, ...],
    top_k: int,
    backend: str | None,
) -> None:
    """Search the memory store."""
    console = Console()
    query_text = " ".join(query)

    mem = _get_backend(backend)
    try:
        results = mem.retrieve(query_text, top_k=top_k)
    finally:
        if hasattr(mem, "close"):
            mem.close()

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search: {query_text}")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", width=8)
    table.add_column("Source", style="cyan")
    table.add_column("Content")

    for i, r in enumerate(results, 1):
        # Truncate content for display
        preview = r.content[:200]
        if len(r.content) > 200:
            preview += "..."
        table.add_row(
            str(i),
            f"{r.score:.4f}",
            r.source or "-",
            preview,
        )

    console.print(table)


@memory.command()
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
def stats(backend: str | None) -> None:
    """Show memory store statistics."""
    console = Console()

    mem = _get_backend(backend)
    try:
        count = 0
        if hasattr(mem, "count"):
            count = mem.count()

        table = Table(title="Memory Statistics")
        table.add_column("Property", style="cyan")
        table.add_column("Value")
        table.add_row("Backend", mem.backend_id)
        table.add_row("Documents", str(count))

        if hasattr(mem, "_db_path"):
            db_path = Path(mem._db_path)
            if db_path.exists():
                size_kb = db_path.stat().st_size / 1024
                table.add_row(
                    "Database size",
                    f"{size_kb:.1f} KB",
                )
            table.add_row("Database path", str(db_path))

        console.print(table)
    finally:
        if hasattr(mem, "close"):
            mem.close()
