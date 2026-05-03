"""``serena wordpress`` - native WordPress website/content operations."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_wordpress import (
    SerenaWordPressBuildPagePlanTool,
    SerenaWordPressCreateDraftTool,
    SerenaWordPressCreatePageTool,
    SerenaWordPressStatusTool,
)


@click.group()
def wordpress() -> None:
    """Native Serena WordPress website/content tools."""
    pass


@wordpress.command("status")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
def status(site_key: str | None) -> None:
    """Check WordPress connection/config status."""
    console = Console()
    result = SerenaWordPressStatusTool().execute(site_key=site_key)
    if result.success:
        console.print(result.content)
    else:
        console.print(f"[red]{result.content}[/red]")


@wordpress.command("plan")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--page-type", default="landing page", help="Page type, e.g. service page, landing page.")
@click.option("--topic", required=True, help="Main page topic or service.")
@click.option("--audience", default="website visitors", help="Target audience.")
@click.option("--goal", default="Book your consultation", help="Primary conversion goal.")
@click.option("--healthcare/--no-healthcare", default=True, help="Whether healthcare compliance notes are needed.")
def plan(
    site_key: str | None,
    page_type: str,
    topic: str,
    audience: str,
    goal: str,
    healthcare: bool,
) -> None:
    """Build a WordPress page/landing-page plan without writing to WordPress."""
    console = Console()
    result = SerenaWordPressBuildPagePlanTool().execute(
        site_key=site_key,
        page_type=page_type,
        topic=topic,
        audience=audience,
        goal=goal,
        healthcare=healthcare,
    )

    if result.success:
        console.print(result.content)
    else:
        console.print(f"[red]{result.content}[/red]")


@wordpress.command("draft")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--title", required=True, help="Draft post title.")
@click.option("--content", required=True, help="Draft post content. HTML or plain text.")
@click.option("--slug", default="", help="Optional slug.")
def draft(site_key: str | None, title: str, content: str, slug: str) -> None:
    """Create a WordPress post draft."""
    console = Console()
    result = SerenaWordPressCreateDraftTool().execute(
        site_key=site_key,
        title=title,
        content=content,
        slug=slug,
    )

    if result.success:
        console.print(result.content)
    else:
        console.print(f"[red]{result.content}[/red]")


@wordpress.command("page")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--title", required=True, help="Page title.")
@click.option("--content", required=True, help="Page content. HTML or plain text.")
@click.option("--slug", default="", help="Optional slug.")
@click.option("--status", default="draft", help="Page status. Defaults to draft.")
@click.option("--approved", is_flag=True, help="Required if status is publish.")
def page(
    site_key: str | None,
    title: str,
    content: str,
    slug: str,
    status: str,
    approved: bool,
) -> None:
    """Create a WordPress page, draft by default."""
    console = Console()
    result = SerenaWordPressCreatePageTool().execute(
        site_key=site_key,
        title=title,
        content=content,
        slug=slug,
        status=status,
        approved=approved,
    )

    if result.success:
        console.print(result.content)
    else:
        console.print(f"[red]{result.content}[/red]")


__all__ = ["wordpress"]
