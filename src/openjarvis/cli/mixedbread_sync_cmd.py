"""``jarvis mixedbread-sync`` — mirror the knowledge base to Mixedbread.

Uploads every live ``knowledge_chunks`` row to the configured Mixedbread
store so ``[deep_research] retrieval = "mixedbread"`` (toast-1 agentic
search) has a corpus to search.  Idempotent: chunks are keyed by
``external_id`` and overwritten, so re-running after new connector syncs
only refreshes content.

This sends knowledge-base content to the Mixedbread cloud API — it is
never run implicitly.
"""

from __future__ import annotations

from typing import Optional

import click

from openjarvis.core.config import load_config


@click.command("mixedbread-sync")
@click.option(
    "--store-name",
    default=None,
    help="Mixedbread store to mirror into (default: [deep_research].mixedbread_store).",
)
@click.option(
    "--db",
    "knowledge_db",
    default=None,
    type=click.Path(),
    help="Path to the knowledge SQLite db (default: the configured location).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Count the chunks that would be uploaded without uploading.",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Skip the cloud-upload confirmation prompt.",
)
def mixedbread_sync(
    store_name: Optional[str],
    knowledge_db: Optional[str],
    dry_run: bool,
    yes: bool,
) -> None:
    """Mirror the Deep Research knowledge base to a Mixedbread store."""
    from openjarvis.connectors.mixedbread_search import MixedbreadKnowledgeSync
    from openjarvis.connectors.store import KnowledgeStore

    config = load_config()
    resolved_store = store_name or config.deep_research.mixedbread_store

    store_kwargs: dict = {}
    if knowledge_db:
        store_kwargs["db_path"] = knowledge_db
    store = KnowledgeStore(**store_kwargs)

    if not dry_run and not yes:
        click.confirm(
            f"Upload the local knowledge base to Mixedbread store "
            f"'{resolved_store}' (cloud)?",
            abort=True,
        )

    try:
        try:
            sync = MixedbreadKnowledgeSync(store, store_name=resolved_store)
        except (ImportError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        try:
            report = sync.sync(dry_run=dry_run)
        finally:
            sync.close()
    finally:
        store.close()

    if report.dry_run:
        click.echo(f"{report.total} chunk(s) would be uploaded to '{resolved_store}'.")
        return
    click.echo(
        f"Synced {report.uploaded}/{report.total} chunk(s) to '{resolved_store}'"
        + (f" ({report.failed} failed)" if report.failed else "")
        + (f"; deleted {report.deleted} stale chunk(s)" if report.deleted else "")
        + (
            f" ({report.delete_failed} deletion failure(s))"
            if report.delete_failed
            else ""
        )
        + "."
    )
    if report.failed or report.delete_failed:
        raise SystemExit(1)


__all__ = ["mixedbread_sync"]
