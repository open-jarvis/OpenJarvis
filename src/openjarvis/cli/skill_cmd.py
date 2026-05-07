"""CLI commands for skill management."""

from __future__ import annotations

from pathlib import Path
from typing import List

import click
from rich.console import Console
from rich.table import Table

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.skills.manager import SkillManager


def _get_trace_store():
    """Return a TraceStore instance from the user config (or None)."""
    try:
        from openjarvis.core.config import load_config
        from openjarvis.traces.store import TraceStore

        cfg = load_config()
        return TraceStore(cfg.traces.db_path)
    except Exception:
        return None


def _get_discovered_dir() -> Path:
    """Return the directory where discovered skill manifests are written."""
    return Path("~/.openjarvis/skills/discovered/").expanduser()


def _get_overlay_dir() -> Path:
    """Return the directory where optimization overlays are stored."""
    return Path("~/.openjarvis/learning/skills/").expanduser()


def _get_skill_paths() -> List[Path]:
    paths: List[Path] = []
    workspace = Path("./skills")
    if workspace.exists():
        paths.append(workspace)
    user_dir = Path("~/.openjarvis/skills/").expanduser()
    paths.append(user_dir)
    return paths


def _get_manager() -> SkillManager:
    mgr = SkillManager(bus=EventBus())
    mgr.discover(paths=_get_skill_paths())
    return mgr


@click.group()
def skill():
    """Manage reusable skills."""


@skill.command("list")
def list_skills():
    """List installed skills."""
    console = Console()
    mgr = _get_manager()
    names = mgr.skill_names()
    if not names:
        console.print("[dim]No skills installed.[/dim]")
        return
    table = Table(title="Installed Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Description", max_width=50)
    table.add_column("Version")
    table.add_column("Tags")
    for name in sorted(names):
        m = mgr.resolve(name)
        tags = ", ".join(m.tags) if m.tags else ""
        desc = m.description[:50] + "..." if len(m.description) > 50 else m.description
        table.add_row(name, desc, m.version, tags)
    console.print(table)


@skill.command("info")
@click.argument("skill_name")
def info(skill_name: str):
    """Show detailed information about a skill."""
    console = Console()
    mgr = _get_manager()
    try:
        m = mgr.resolve(skill_name)
    except KeyError:
        console.print(f"[red]Skill '{skill_name}' not found.[/red]")
        raise SystemExit(1)
    console.print(f"[bold]{m.name}[/bold] v{m.version}")
    if m.author:
        console.print(f"Author: {m.author}")
    if m.description:
        console.print(f"Description: {m.description}")
    if m.tags:
        console.print(f"Tags: {', '.join(m.tags)}")
    if m.required_capabilities:
        console.print(f"Capabilities: {', '.join(m.required_capabilities)}")
    if m.depends:
        console.print(f"Dependencies: {', '.join(m.depends)}")
    if m.steps:
        console.print(f"Steps: {len(m.steps)}")
    if m.markdown_content:
        console.print("Has instructions: yes")
    console.print(f"User invocable: {m.user_invocable}")
    console.print(
        f"Model invocation: {'disabled' if m.disable_model_invocation else 'enabled'}"
    )


@skill.command("run")
@click.argument("skill_name")
@click.option("--arg", "-a", multiple=True, help="Arguments as key=value pairs.")
def run(skill_name: str, arg: tuple):
    """Execute a skill directly."""
    console = Console()
    mgr = _get_manager()
    context = {}
    for a in arg:
        if "=" in a:
            k, v = a.split("=", 1)
            context[k.strip()] = v.strip()
    try:
        result = mgr.execute(skill_name, context)
    except KeyError:
        console.print(f"[red]Skill '{skill_name}' not found.[/red]")
        raise SystemExit(1)
    if result.success:
        console.print("[green]Success[/green]")
        if result.step_results:
            console.print(result.step_results[-1].content)
    else:
        console.print("[red]Failed[/red]")
        if result.step_results:
            console.print(result.step_results[-1].content)


def _parse_source_query(query: str) -> tuple[str, str]:
    """Parse a ``<source>:<name>`` query into (source, name).

    Raises ``click.BadParameter`` if the format is wrong.
    """
    if ":" not in query:
        raise click.BadParameter(
            f"Expected '<source>:<name>' format (e.g. 'hermes:apple-notes'), "
            f"got: {query!r}"
        )
    source, _, name = query.partition(":")
    if not source or not name:
        raise click.BadParameter(
            f"Both source and name are required: got source={source!r}, name={name!r}"
        )
    return source, name


def _get_resolver(source: str, url: str = ""):
    """Return a resolver instance for the given source name."""
    if source == "hermes":
        from openjarvis.skills.sources.hermes import HermesResolver

        return HermesResolver()
    if source == "openclaw":
        from openjarvis.skills.sources.openclaw import OpenClawResolver

        return OpenClawResolver()
    if source == "github":
        if not url:
            raise click.BadParameter("github source requires --url")
        from pathlib import Path as _Path

        from openjarvis.skills.sources.github import GitHubResolver

        cache = _Path(
            "~/.openjarvis/skill-cache/github/" + url.rstrip("/").rsplit("/", 1)[-1]
        ).expanduser()
        return GitHubResolver(cache_root=cache, repo_url=url)
    raise click.BadParameter(f"Unknown source: {source!r}")


@skill.command("install")
@click.argument("query")
@click.option(
    "--with-scripts",
    is_flag=True,
    default=False,
    help="Import the skill's scripts/ directory (security-sensitive).",
)
@click.option(
    "--force", is_flag=True, default=False, help="Overwrite existing install."
)
@click.option(
    "--url",
    default="",
    help="Repo URL (required when source is 'github').",
)
def install(query: str, with_scripts: bool, force: bool, url: str):
    """Install a skill from a source.

    Example: ``jarvis skill install hermes:apple-notes``
    """
    console = Console()
    source, name = _parse_source_query(query)

    resolver = _get_resolver(source, url=url)
    try:
        resolver.sync()
    except Exception as exc:
        console.print(f"[red]Failed to sync source {source}: {exc}[/red]")
        raise SystemExit(1)

    # Support category/name queries (e.g. openclaw:owner/slug, hermes:apple/apple-notes)
    if "/" in name:
        category, _, skill_name = name.partition("/")
        matches = [
            s
            for s in resolver.list_skills()
            if s.name == skill_name and s.category == category
        ]
    else:
        matches = [s for s in resolver.list_skills() if s.name == name]
    if not matches:
        console.print(f"[red]No skill named '{name}' found in source '{source}'[/red]")
        raise SystemExit(1)

    from openjarvis.skills.importer import SkillImporter
    from openjarvis.skills.parser import SkillParser
    from openjarvis.skills.tool_translator import ToolTranslator

    importer = SkillImporter(parser=SkillParser(), tool_translator=ToolTranslator())
    result = importer.import_skill(matches[0], with_scripts=with_scripts, force=force)

    if result.success:
        if result.skipped:
            console.print("[yellow]Skill already installed[/yellow]")
        else:
            console.print(f"[green]Installed:[/green] {result.target_path}")
        if result.translated_tools:
            console.print(f"  Translated tools: {', '.join(result.translated_tools)}")
        if result.untranslated_tools:
            console.print(
                f"  [yellow]Untranslated tools:[/yellow] "
                f"{', '.join(result.untranslated_tools)}"
            )
        for warning in result.warnings:
            console.print(f"  [yellow]{warning}[/yellow]")
    else:
        console.print(
            "[red]Install failed: "
            + "; ".join(result.warnings or ["unknown error"])
            + "[/red]"
        )
        raise SystemExit(1)


@skill.command("sync")
@click.argument("source", required=False)
@click.option("--category", default="", help="Filter by category.")
@click.option("--tag", default="", help="Filter by tag.")
@click.option("--search", default="", help="Substring search across name+description.")
@click.option(
    "--with-scripts",
    is_flag=True,
    default=False,
    help="Import scripts/ directories.",
)
@click.option("--force", is_flag=True, default=False, help="Re-import existing skills.")
def sync(
    source: str,
    category: str,
    tag: str,
    search: str,
    with_scripts: bool,
    force: bool,
):
    """Bulk install + update from a source (or all configured sources)."""
    console = Console()

    cfg = load_config()

    # Determine which sources to sync
    source_configs: list = []
    if source:
        source_configs.append({"source": source, "filter": {}, "url": ""})
    else:
        for src_cfg in cfg.skills.sources:
            source_configs.append(
                {
                    "source": src_cfg.source,
                    "filter": dict(src_cfg.filter or {}),
                    "url": src_cfg.url,
                }
            )

    if not source_configs:
        console.print(
            "[yellow]No sources to sync. "
            "Add sources to [skills.sources] in config.toml "
            "or pass a source name.[/yellow]"
        )
        return

    from openjarvis.skills.importer import SkillImporter
    from openjarvis.skills.parser import SkillParser
    from openjarvis.skills.tool_translator import ToolTranslator

    importer = SkillImporter(parser=SkillParser(), tool_translator=ToolTranslator())

    total_installed = 0
    for src in source_configs:
        console.print(f"[cyan]Syncing {src['source']}...[/cyan]")
        try:
            resolver = _get_resolver(src["source"], url=src["url"])
            resolver.sync()
        except Exception as exc:
            console.print(f"[red]Failed to sync {src['source']}: {exc}[/red]")
            continue

        skills_to_import = resolver.list_skills()

        # Apply CLI filters
        if category:
            skills_to_import = [s for s in skills_to_import if s.category == category]
        if search:
            sl = search.lower()
            skills_to_import = [
                s
                for s in skills_to_import
                if sl in s.name.lower() or sl in s.description.lower()
            ]

        # Apply config filter (categories list)
        cfg_categories = src["filter"].get("category") or []
        if cfg_categories:
            skills_to_import = [
                s for s in skills_to_import if s.category in cfg_categories
            ]

        installed_count = 0
        for resolved in skills_to_import:
            r = importer.import_skill(resolved, with_scripts=with_scripts, force=force)
            if r.success and not r.skipped:
                installed_count += 1
        console.print(f"  Imported {installed_count}/{len(skills_to_import)} skills")
        total_installed += installed_count

    console.print(f"[green]Total installed: {total_installed}[/green]")


@skill.command("sources")
def sources():
    """List configured skill sources."""
    console = Console()

    cfg = load_config()

    if not cfg.skills.sources:
        console.print(
            "[dim]No skill sources configured. "
            "Add entries to [skills.sources] in config.toml.[/dim]"
        )
        return

    table = Table(title="Configured Skill Sources")
    table.add_column("Source", style="cyan")
    table.add_column("URL")
    table.add_column("Filter")
    table.add_column("Auto-update")
    for s in cfg.skills.sources:
        filt = ", ".join(f"{k}={v}" for k, v in (s.filter or {}).items()) or "—"
        table.add_row(
            s.source,
            s.url or "(default)",
            filt,
            "yes" if s.auto_update else "no",
        )
    console.print(table)


@skill.command("remove")
@click.argument("skill_name")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt.",
)
def remove(skill_name: str, yes: bool):
    """Remove an installed skill by name.

    Searches ``~/.openjarvis/skills/`` and ``./skills`` for a directory whose
    name (or parsed manifest name) matches ``skill_name`` and deletes it.
    """
    console = Console()
    mgr = SkillManager(bus=EventBus())
    paths = mgr.find_installed_paths(skill_name, roots=_get_skill_paths())
    if not paths:
        console.print(f"[red]No installed skill named '{skill_name}' found.[/red]")
        raise SystemExit(1)

    console.print(f"[bold]Will remove {len(paths)} location(s):[/bold]")
    for p in paths:
        console.print(f"  - {p}")

    if not yes:
        if not click.confirm("Proceed?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return

    try:
        removed = mgr.remove(skill_name, roots=_get_skill_paths())
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    for p in removed:
        console.print(f"[green]Removed:[/green] {p}")


@skill.command("search")
@click.argument("query")
@click.option(
    "--source",
    "-s",
    default="",
    help="Restrict search to a single configured source.",
)
def search(query: str, source: str):
    """Search available skills across configured sources.

    Matches ``query`` (case-insensitive substring) against skill name,
    description, and tags.
    """
    console = Console()
    cfg = load_config()

    if not cfg.skills.sources:
        console.print(
            "[yellow]No skill sources configured. "
            "Add entries to [skills.sources] in config.toml.[/yellow]"
        )
        raise SystemExit(1)

    sources_to_search = [
        s for s in cfg.skills.sources if not source or s.source == source
    ]
    if source and not sources_to_search:
        console.print(f"[red]No configured source named '{source}'.[/red]")
        raise SystemExit(1)

    q = query.lower().strip()
    rows: list[tuple[str, str, str, str]] = []  # source, name, category, description
    for src_cfg in sources_to_search:
        try:
            resolver = _get_resolver(src_cfg.source, url=src_cfg.url)
            resolver.sync()
        except Exception as exc:
            console.print(f"[yellow]Skipped {src_cfg.source}: {exc}[/yellow]")
            continue

        for resolved in resolver.list_skills():
            haystack = " ".join(
                [
                    resolved.name or "",
                    resolved.description or "",
                    resolved.category or "",
                ]
            ).lower()
            if q in haystack:
                rows.append(
                    (
                        src_cfg.source,
                        resolved.name,
                        getattr(resolved, "category", "") or "",
                        (getattr(resolved, "description", "") or "")[:60],
                    )
                )

    if not rows:
        console.print(f"[dim]No skills matching '{query}'.[/dim]")
        return

    table = Table(title=f"Search results for '{query}'")
    table.add_column("Source", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Category")
    table.add_column("Description", max_width=60)
    for row in rows:
        table.add_row(*row)
    console.print(table)
    console.print(
        f"[dim]{len(rows)} match(es). "
        f"Install with: jarvis skill install <source>:<name>[/dim]"
    )


@skill.command("update")
def update():
    """Pull latest commits for all installed skill sources."""
    console = Console()

    cfg = load_config()
    if not cfg.skills.sources:
        console.print("[dim]No sources configured.[/dim]")
        return

    for src in cfg.skills.sources:
        console.print(f"[cyan]Updating {src.source}...[/cyan]")
        try:
            resolver = _get_resolver(src.source, url=src.url)
            resolver.sync()
            console.print("  [green]OK[/green]")
        except Exception as exc:
            console.print(f"  [red]Failed: {exc}[/red]")


@skill.command("discover")
@click.option(
    "--min-frequency",
    "-f",
    default=3,
    show_default=True,
    type=int,
    help="Minimum recurrence count to surface a tool sequence as a skill.",
)
@click.option(
    "--min-outcome",
    "-o",
    default=0.5,
    show_default=True,
    type=float,
    help="Minimum average outcome score (0.0-1.0) to qualify.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print discovered patterns without writing manifests.",
)
def discover(min_frequency: int, min_outcome: float, dry_run: bool) -> None:
    """Mine the trace store for recurring tool sequences and write them as
    discovered skill manifests under ~/.openjarvis/skills/discovered/."""
    console = Console()
    store = _get_trace_store()
    if store is None:
        console.print(
            "[red]No trace store found. "
            "Enable tracing in config (traces.enabled = true) and run "
            "some queries first.[/red]"
        )
        raise SystemExit(1)

    output_dir = _get_discovered_dir()
    mgr = SkillManager(bus=EventBus())

    if dry_run:
        # Use a temporary directory so nothing is persisted
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="openjarvis-discover-dryrun-"))
        try:
            written = mgr.discover_from_traces(
                store,
                min_frequency=min_frequency,
                min_outcome=min_outcome,
                output_dir=tmp,
            )
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
    else:
        written = mgr.discover_from_traces(
            store,
            min_frequency=min_frequency,
            min_outcome=min_outcome,
            output_dir=output_dir,
        )

    if not written:
        console.print(
            "[dim]No recurring tool sequences found above the threshold.[/dim]"
        )
        return

    table = Table(title="Discovered Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Path")
    for item in written:
        table.add_row(item["name"], item["path"])
    console.print(table)
    if dry_run:
        console.print("[yellow]--dry-run: no files were written.[/yellow]")


@skill.command("show-overlay")
@click.argument("skill_name")
def show_overlay(skill_name: str) -> None:
    """Show the optimization overlay for a skill, if one exists."""
    console = Console()
    from openjarvis.skills.overlay import SkillOverlayLoader

    loader = SkillOverlayLoader(_get_overlay_dir())
    overlay = loader.load(skill_name)
    if overlay is None:
        console.print(f"[red]No overlay found for skill '{skill_name}'.[/red]")
        raise SystemExit(1)

    console.print(f"[bold]{overlay.skill_name}[/bold]")
    console.print(f"Optimizer: {overlay.optimizer}")
    console.print(f"Optimized at: {overlay.optimized_at}")
    console.print(f"Trace count: {overlay.trace_count}")
    console.print(f"Description: {overlay.description}")
    if overlay.few_shot:
        console.print(f"Few-shot examples ({len(overlay.few_shot)}):")
        for i, ex in enumerate(overlay.few_shot, start=1):
            inp = (ex.get("input", "") or "")[:100]
            out = (ex.get("output", "") or "")[:100]
            console.print(f"  {i}. input={inp!r}")
            console.print(f"     output={out!r}")


__all__ = ["skill"]
