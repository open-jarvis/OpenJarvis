"""``serena wordpress`` - native WordPress website/content operations."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_wordpress import (
    SerenaWordPressBuildPagePlanTool,
    SerenaWordPressCreateDraftTool,
    SerenaWordPressCreatePageTool,
    SerenaWordPressGetContentTool,
    SerenaWordPressInspectContentTool,
    SerenaWordPressListPagesTool,
    SerenaWordPressListPostsTool,
    SerenaWordPressSearchTool,
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


@wordpress.command("list-posts")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--limit", default=10, type=int, help="Number of posts to list.")
@click.option("--status", default="any", help="Post status filter.")
@click.option("--search", default="", help="Optional search query.")
def list_posts(site_key: str | None, limit: int, status: str, search: str) -> None:
    """List WordPress posts."""
    console = Console()
    result = SerenaWordPressListPostsTool().execute(
        site_key=site_key,
        limit=limit,
        status=status,
        search=search,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("list-pages")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--limit", default=10, type=int, help="Number of pages to list.")
@click.option("--status", default="any", help="Page status filter.")
@click.option("--search", default="", help="Optional search query.")
def list_pages(site_key: str | None, limit: int, status: str, search: str) -> None:
    """List WordPress pages."""
    console = Console()
    result = SerenaWordPressListPagesTool().execute(
        site_key=site_key,
        limit=limit,
        status=status,
        search=search,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("search")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--query", required=True, help="Search query.")
@click.option("--limit", default=5, type=int, help="Max results per content type.")
def search(site_key: str | None, query: str, limit: int) -> None:
    """Search WordPress posts and pages."""
    console = Console()
    result = SerenaWordPressSearchTool().execute(
        site_key=site_key,
        query=query,
        limit=limit,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("get")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--type", "content_type", default="pages", help="Content type: posts or pages.")
@click.option("--id", "content_id", required=True, type=int, help="WordPress post/page ID.")
@click.option("--include-content", is_flag=True, help="Include rendered HTML content.")
def get_content(site_key: str | None, content_type: str, content_id: int, include_content: bool) -> None:
    """Get a WordPress post/page by ID."""
    console = Console()
    result = SerenaWordPressGetContentTool().execute(
        site_key=site_key,
        content_type=content_type,
        content_id=content_id,
        include_content=include_content,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("inspect")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--type", "content_type", default="pages", help="Content type: posts or pages.")
@click.option("--id", "content_id", required=True, type=int, help="WordPress post/page ID.")
@click.option("--keyword", default="", help="Optional target SEO keyword.")
@click.option("--healthcare/--no-healthcare", default=True, help="Whether healthcare compliance review is needed.")
def inspect_content(
    site_key: str | None,
    content_type: str,
    content_id: int,
    keyword: str,
    healthcare: bool,
) -> None:
    """Inspect a WordPress post/page like a developer/operator."""
    console = Console()
    result = SerenaWordPressInspectContentTool().execute(
        site_key=site_key,
        content_type=content_type,
        content_id=content_id,
        keyword=keyword,
        healthcare=healthcare,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["wordpress"]
