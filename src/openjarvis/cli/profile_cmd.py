"""``jarvis profile`` — inspect and rebuild the user profile."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from openjarvis.core.config import load_config
from openjarvis.personalization.consolidator import (
    consolidate_from_config,
)
from openjarvis.personalization.profile import (
    DEFAULT_PROFILE_PATH,
    UserProfile,
)
from openjarvis.personalization.tool_affinity import ToolAffinityTracker


@click.group(help="管理使用者輪廓 (USER.md) 與工具使用偏好。")
def profile() -> None:
    """Profile management commands."""


@profile.command("show")
@click.option(
    "--path",
    "profile_path",
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
    help="Path to USER.md.",
)
def show_cmd(profile_path: str) -> None:
    """顯示目前 USER.md 內容。"""
    console = Console()
    path = Path(profile_path).expanduser()
    if not path.exists():
        console.print(f"[yellow]找不到 profile：[/yellow]{path}")
        console.print("跑 [bold]jarvis profile rebuild[/bold] 從 memory.db 建一份。")
        return
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        console.print(f"[yellow]profile 是空的：[/yellow]{path}")
        return
    console.print(Markdown(text))


@profile.command("rebuild")
@click.option(
    "--path",
    "profile_path",
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
    help="Output path.",
)
@click.option(
    "--yes",
    is_flag=True,
    help="不要互動確認，直接覆寫。",
)
def rebuild_cmd(profile_path: str, yes: bool) -> None:
    """從 memory.db 重新整理 USER.md。"""
    console = Console()
    target = Path(profile_path).expanduser()
    if target.exists() and not yes:
        console.print(f"[yellow]會覆寫：[/yellow]{target}")
        if not click.confirm("確定要繼續嗎？", default=False):
            console.print("[dim]取消。[/dim]")
            return

    config = load_config()
    profile, stats = consolidate_from_config(config, output_path=target)
    if stats.scanned == 0:
        console.print(
            "[yellow]memory.db 沒有任何資料。先用 [bold]memory_learn[/bold] "
            "工具教 Jarvis 幾件關於你的事，再回來跑這個指令。[/yellow]"
        )
        return

    console.print(f"[green]profile 已寫入：[/green]{stats.profile_path}")

    table = Table(show_header=False, border_style="cyan")
    table.add_row("掃描", str(stats.scanned))
    table.add_row("採用", str(stats.accepted))
    table.add_row("重複略過", str(stats.skipped_duplicate))
    table.add_row("沒有 key 略過", str(stats.skipped_no_key))
    console.print(table)


@profile.command("edit")
@click.option(
    "--path",
    "profile_path",
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
)
def edit_cmd(profile_path: str) -> None:
    """用 $EDITOR 打開 USER.md。"""
    console = Console()
    path = Path(profile_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        UserProfile().save(path)
    import os

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    try:
        subprocess.call([editor, str(path)])
    except FileNotFoundError:
        console.print(f"[red]找不到編輯器：[/red]{editor}")
        sys.exit(1)


@profile.command("clear")
@click.option(
    "--path",
    "profile_path",
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
)
@click.option("--yes", is_flag=True)
def clear_cmd(profile_path: str, yes: bool) -> None:
    """清空 USER.md（保留檔案，內容歸零）。"""
    console = Console()
    path = Path(profile_path).expanduser()
    if not path.exists():
        console.print("[dim]檔案不存在，沒事做。[/dim]")
        return
    if not yes and not click.confirm(f"清空 {path}？", default=False):
        return
    UserProfile().save(path)
    console.print(f"[green]已清空：[/green]{path}")


@profile.command("tools")
@click.option(
    "--recent-days",
    default=None,
    type=float,
    help="只看最近 N 天的記錄。",
)
@click.option("--limit", default=10, show_default=True)
def tools_cmd(recent_days: float | None, limit: int) -> None:
    """看你最常用的工具。"""
    console = Console()
    tracker = ToolAffinityTracker()
    top = tracker.top_tools(limit=limit, recent_days=recent_days)
    if not top:
        console.print("[dim]還沒有工具使用紀錄。[/dim]")
        return
    table = Table(
        title="工具使用偏好",
        header_style="bold bright_white",
        border_style="bright_blue",
    )
    table.add_column("工具", style="cyan")
    table.add_column("用量", justify="right")
    table.add_column("成功率", justify="right")
    for name, count, rate in top:
        table.add_row(name, str(count), f"{rate:.0%}")
    console.print(table)


__all__ = ["profile"]
