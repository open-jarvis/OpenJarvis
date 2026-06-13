"""``jarvis osint`` — OSINT Arsenal & FBI Watchdog commands."""

from __future__ import annotations

import json
from typing import Any

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("osint")
def osint() -> None:
    """OSINT Arsenal and FBI Watchdog reconnaissance commands."""


@osint.command("search")
@click.argument("query")
@click.option("--limit", default=5, type=int, help="Max results (default 5).")
@click.option("--category", default="", help="Category filter.")
def search(query: str, limit: int, category: str) -> None:
    """Search the OSINT Arsenal knowledge base for tools."""
    from openjarvis.tools.osint_arsenal.search_tool import _ensure_index, _score

    index = _ensure_index()
    if not index:
        console.print("[red]OSINT Arsenal index not found.[/red]")
        return

    import re

    query_words = set(re.findall(r"[a-zA-Z0-9]+", query.lower()))
    if not query_words:
        query_words = {query.lower()}

    scored = []
    for tool in index:
        if category and category.lower() not in tool.get("category", "").lower():
            continue
        score = _score(tool, query_words)
        if score > 0:
            scored.append((score, tool))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    if not top:
        console.print(f"[yellow]No tools found for '{query}'.[/yellow]")
        return

    table = Table(title=f"OSINT Arsenal: '{query}'")
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("Tool", style="bold")
    table.add_column("Category", style="dim")
    table.add_column("Description")
    table.add_column("Link / Install")

    for rank, (_, tool) in enumerate(top, 1):
        link = tool.get("url") or tool.get("install_command") or "-"
        table.add_row(
            str(rank),
            tool["name"],
            tool["category"],
            tool["description"][:60] + "…" if len(tool["description"]) > 60 else tool["description"],
            link,
        )

    console.print(table)


@osint.command("watch")
@click.argument("target")
@click.option(
    "--modules",
    default="dns,http,whois,ip",
    help="Comma-separated modules (default: dns,http,whois,ip).",
)
@click.option("--json-out", is_flag=True, help="Output raw JSON.")
def watch(target: str, modules: str, json_out: bool) -> None:
    """Run an FBI Watchdog reconnaissance scan on a target."""
    from openjarvis.tools.fbi_watchdog.core import run_scan

    module_list = [m.strip() for m in modules.split(",") if m.strip()]
    results = run_scan(target, module_list)

    if json_out:
        click.echo(json.dumps(results, indent=2, default=str))
        return

    console.print(f"[bold green]OSINT Recon: {target}[/bold green]")
    console.print()

    for mod, mod_result in results["results"].items():
        console.print(f"[bold cyan]{mod.upper()}[/bold cyan]")
        if mod_result.get("errors"):
            console.print(f"  [red]Errors: {', '.join(mod_result['errors'])}[/red]")

        if mod == "dns" and mod_result.get("records"):
            for record_type, records in mod_result["records"].items():
                console.print(f"  {record_type}: {', '.join(records)}")
        elif mod == "http":
            console.print(f"  Reachable: {mod_result.get('reachable')}")
            console.print(f"  Status: {mod_result.get('status_code')}")
            console.print(f"  Final URL: {mod_result.get('final_url')}")
            if mod_result.get("headers"):
                for key, val in mod_result["headers"].items():
                    console.print(f"  {key}: {val}")
        elif mod == "whois":
            console.print(f"  Registrar: {mod_result.get('registrar')}")
            console.print(f"  Privacy Protected: {mod_result.get('privacy_protected')}")
        elif mod == "ip":
            console.print(f"  Reverse DNS: {mod_result.get('reverse_dns')}")
            geo = mod_result.get("geolocation", {})
            if geo.get("country"):
                console.print(f"  Country: {geo['country']}")
            if geo.get("city"):
                console.print(f"  City: {geo['city']}")
            if geo.get("isp"):
                console.print(f"  ISP: {geo['isp']}")

        console.print()

    summary = results["summary"]
    console.print("[bold]Summary:[/bold]")
    console.print(f"  Reachable: {summary['reachable']}")
    console.print(f"  Privacy Protected: {summary['privacy_protected']}")
    console.print(f"  Seizure Detected: {summary['seizure_detected']}")
    console.print(f"  Errors: {summary['errors']}")


__all__ = ["osint"]
