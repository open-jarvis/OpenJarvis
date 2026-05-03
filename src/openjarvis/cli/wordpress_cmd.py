"""``serena wordpress`` - native WordPress website/content operations."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_wordpress import (
    SerenaWordPressBuildPagePlanTool,
    SerenaWordPressContentListTool,
    SerenaWordPressContentInspectTool,
    SerenaWordPressContentCreateTool,
    SerenaWordPressBuildPageFromLibraryTool,
    SerenaWordPressCreateDraftTool,
    SerenaWordPressCreatePageTool,
    SerenaWordPressGetContentTool,
    SerenaWordPressInspectContentTool,
    SerenaWordPressListPagesTool,
    SerenaWordPressListPostsTool,
    SerenaWordPressSearchTool,
    SerenaWordPressStatusTool,
    SerenaWordPressTrashContentTool,
    SerenaWordPressUpdateContentTool,
    SerenaWordPressUploadMediaTool,
    SerenaWordPressSetFeaturedImageTool,
    SerenaWordPressAssignTermsTool,
    SerenaWordPressCreateTagTool,
    SerenaWordPressCreateCategoryTool,
    SerenaWordPressListTagsTool,
    SerenaWordPressListCategoriesTool,
    SerenaWordPressMediaImportTool,
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


@wordpress.command("update")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--type", "content_type", default="pages", help="Content type: posts or pages.")
@click.option("--id", "content_id", required=True, type=int, help="WordPress post/page ID.")
@click.option("--title", default="", help="Optional new title.")
@click.option("--content", default="", help="Optional new content. HTML or plain text.")
@click.option("--status", default="", help="Optional status. Publishing requires --approved.")
@click.option("--approved", is_flag=True, help="Required only when status=publish.")
def update_content(
    site_key: str | None,
    content_type: str,
    content_id: int,
    title: str,
    content: str,
    status: str,
    approved: bool,
) -> None:
    """Update a WordPress post/page. Saves rollback snapshot first."""
    console = Console()

    result = SerenaWordPressUpdateContentTool().execute(
        site_key=site_key,
        content_type=content_type,
        content_id=content_id,
        title=title,
        content=content,
        status=status,
        approved=approved,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("media")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--path", "file_path", required=True, help="Local media file path.")
@click.option("--title", default="", help="Optional media title.")
@click.option("--alt-text", default="", help="Optional alt text.")
def media(site_key: str | None, file_path: str, title: str, alt_text: str) -> None:
    """Upload media to WordPress from a local/content-library path."""
    console = Console()

    result = SerenaWordPressUploadMediaTool().execute(
        site_key=site_key,
        path=file_path,
        title=title,
        alt_text=alt_text,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("publish")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--type", "content_type", default="pages", help="Content type: posts or pages.")
@click.option("--id", "content_id", required=True, type=int, help="WordPress post/page ID.")
@click.option("--approved", is_flag=True, help="Required. Confirms explicit human approval to publish.")
def publish(site_key: str | None, content_type: str, content_id: int, approved: bool) -> None:
    """Publish an existing WordPress post/page only after explicit approval."""
    console = Console()

    if not approved:
        console.print(
            "[red]Publishing requires explicit approval. "
            "Re-run with --approved only after the user confirms publishing.[/red]"
        )
        return

    result = SerenaWordPressUpdateContentTool().execute(
        site_key=site_key,
        content_type=content_type,
        content_id=content_id,
        status="publish",
        approved=True,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("trash")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--type", "content_type", default="pages", help="Content type: posts or pages.")
@click.option("--id", "content_id", required=True, type=int, help="WordPress post/page ID.")
def trash(site_key: str | None, content_type: str, content_id: int) -> None:
    """Move a WordPress post/page to trash. Soft-trash only."""
    console = Console()

    result = SerenaWordPressTrashContentTool().execute(
        site_key=site_key,
        content_type=content_type,
        content_id=content_id,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("content-create")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--title", required=True, help="Content/page title.")
@click.option("--topic", default="", help="Main topic. Defaults to title.")
@click.option("--type", "content_type", default="page", help="Content type: page or post.")
@click.option("--audience", default="website visitors", help="Target audience.")
@click.option("--goal", default="", help="Conversion goal.")
@click.option("--healthcare/--no-healthcare", default=True, help="Whether healthcare compliance language is needed.")
@click.option("--content", default="", help="Optional explicit HTML content. If omitted, Serena creates a starter page.")
def content_create(
    site_key: str | None,
    title: str,
    topic: str,
    content_type: str,
    audience: str,
    goal: str,
    healthcare: bool,
    content: str,
) -> None:
    """Create a local WordPress content-library HTML file."""
    console = Console()

    result = SerenaWordPressContentCreateTool().execute(
        site_key=site_key,
        title=title,
        topic=topic,
        content_type=content_type,
        audience=audience,
        goal=goal,
        healthcare=healthcare,
        content=content,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("content-list")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--limit", default=20, type=int, help="Maximum files to show.")
def content_list(site_key: str | None, limit: int) -> None:
    """List local WordPress content-library files."""
    console = Console()

    result = SerenaWordPressContentListTool().execute(
        site_key=site_key,
        limit=limit,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("content-inspect")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--path", "file_path", required=True, help="Path to HTML file inside the approved content library.")
@click.option("--keyword", default="", help="Optional target SEO keyword.")
@click.option("--healthcare/--no-healthcare", default=True, help="Whether healthcare compliance review is needed.")
def content_inspect(site_key: str | None, file_path: str, keyword: str, healthcare: bool) -> None:
    """Inspect a local WordPress content-library HTML file."""
    console = Console()

    result = SerenaWordPressContentInspectTool().execute(
        site_key=site_key,
        path=file_path,
        keyword=keyword,
        healthcare=healthcare,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("build-page")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--path", "file_path", required=True, help="Path to HTML file inside the approved content library.")
@click.option("--title", required=True, help="WordPress page title.")
@click.option("--slug", default="", help="Optional page slug.")
@click.option("--keyword", default="", help="Optional target SEO keyword.")
@click.option("--healthcare/--no-healthcare", default=True, help="Whether healthcare compliance review is needed.")
def build_page(
    site_key: str | None,
    file_path: str,
    title: str,
    slug: str,
    keyword: str,
    healthcare: bool,
) -> None:
    """Create a WordPress draft page from a content-library file and inspect it."""
    console = Console()

    result = SerenaWordPressBuildPageFromLibraryTool().execute(
        site_key=site_key,
        path=file_path,
        title=title,
        slug=slug,
        keyword=keyword,
        healthcare=healthcare,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("content-update")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--path", "file_path", required=True, help="Path to HTML file inside the approved content library.")
@click.option("--content", required=True, help="Updated HTML content to write to the local content-library file.")
def content_update(site_key: str | None, file_path: str, content: str) -> None:
    """Update a local WordPress content-library HTML file."""
    from pathlib import Path as _Path
    from openjarvis.tools.serena_wordpress import _assert_content_library_path

    console = Console()

    try:
        target = _assert_content_library_path(site_key, _Path(file_path))
        target.write_text(content, encoding="utf-8")
        console.print("[green]WordPress content-library file updated[/green]")
        console.print()
        console.print(f"- File: {target}")
    except Exception as exc:
        console.print(f"[red]Failed to update content-library file: {exc}[/red]")


@wordpress.command("media-import")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--source", "source_path", required=True, help="Existing local media file to copy into Serena's approved media folder.")
@click.option("--title", default="", help="Optional clean media title.")
def media_import(site_key: str | None, source_path: str, title: str) -> None:
    """Import media into Serena's approved local WordPress media folder."""
    console = Console()

    result = SerenaWordPressMediaImportTool().execute(
        site_key=site_key,
        source_path=source_path,
        title=title,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("featured-image")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--type", "content_type", default="pages", help="Content type: posts or pages.")
@click.option("--id", "content_id", required=True, type=int, help="WordPress post/page ID.")
@click.option("--media-id", required=True, type=int, help="WordPress media ID.")
def featured_image(site_key: str | None, content_type: str, content_id: int, media_id: int) -> None:
    """Set a WordPress media item as featured image for a post/page."""
    console = Console()

    result = SerenaWordPressSetFeaturedImageTool().execute(
        site_key=site_key,
        content_type=content_type,
        content_id=content_id,
        media_id=media_id,
    )

    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("list-categories")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--limit", default=20, type=int, help="Maximum categories to show.")
@click.option("--search", default="", help="Optional search query.")
def list_categories(site_key: str | None, limit: int, search: str) -> None:
    """List WordPress categories."""
    console = Console()
    result = SerenaWordPressListCategoriesTool().execute(site_key=site_key, limit=limit, search=search)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("list-tags")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--limit", default=20, type=int, help="Maximum tags to show.")
@click.option("--search", default="", help="Optional search query.")
def list_tags(site_key: str | None, limit: int, search: str) -> None:
    """List WordPress tags."""
    console = Console()
    result = SerenaWordPressListTagsTool().execute(site_key=site_key, limit=limit, search=search)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("category")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--name", required=True, help="Category name to find/create.")
def category(site_key: str | None, name: str) -> None:
    """Find or create a WordPress category."""
    console = Console()
    result = SerenaWordPressCreateCategoryTool().execute(site_key=site_key, name=name)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("tag")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--name", required=True, help="Tag name to find/create.")
def tag(site_key: str | None, name: str) -> None:
    """Find or create a WordPress tag."""
    console = Console()
    result = SerenaWordPressCreateTagTool().execute(site_key=site_key, name=name)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@wordpress.command("assign-terms")
@click.option("--site", "site_key", default=None, help="WordPress site key, e.g. drpiet or serena.")
@click.option("--type", "content_type", default="posts", help="Content type: posts or pages.")
@click.option("--id", "content_id", required=True, type=int, help="WordPress post/page ID.")
@click.option("--categories", default="", help="Comma-separated category names.")
@click.option("--tags", default="", help="Comma-separated tag names.")
def assign_terms(site_key: str | None, content_type: str, content_id: int, categories: str, tags: str) -> None:
    """Assign WordPress categories/tags to a post/page and save rollback snapshot."""
    console = Console()
    result = SerenaWordPressAssignTermsTool().execute(
        site_key=site_key,
        content_type=content_type,
        content_id=content_id,
        categories=categories,
        tags=tags,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["wordpress"]
