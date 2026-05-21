"""Startup banner — arc-reactor logo + OpenJarvis wordmark."""

# ruff: noqa: E501 — Rich markup tags inflate source-line length; the rendered
# banner stays under 80 displayed columns.

from __future__ import annotations

# Reactor on the left (5 lines, ~12 cols) + small ASCII wordmark on the right.
# Last line carries the tagline so the whole block stays under 8 lines / 80 cols.
_BANNER_LINES = (
    r"   [blue]╭─────╮[/blue]      [bold bright_blue] ___                  _                 _    [/]",
    r"  [blue]╱[/blue] [bright_blue]╭───╮[/bright_blue] [blue]╲[/blue]    [bold bright_blue]/ _ \ _ __  ___ _ _  | | __ _ _ ___  _(_)___[/]",
    r" [blue]│[/blue]  [bright_blue]│[/bright_blue] [bold bright_white]◉[/] [bright_blue]│[/bright_blue]  [blue]│[/blue]  [bold bright_blue]| | | | '_ \/ -_) ' \ | |/ _` | '_\ V /| (_-<[/]",
    r"  [blue]╲[/blue] [bright_blue]╰───╯[/bright_blue] [blue]╱[/blue]    [bold bright_blue]\___/| .__/\___|_||_||_|\__,_|_|  \_/ |_/__/[/]",
    r"   [blue]╰─────╯[/blue]          [dim]|_|[/dim]     [cyan]Private AI on your machine[/cyan]",
)

_PLAIN_BANNER = (
    r"   ╭─────╮       ___                  _                 _    ",
    r"  ╱ ╭───╮ ╲     / _ \ _ __  ___ _ _  | | __ _ _ ___  _(_)___ ",
    r" │  │ ◉ │  │   | | | | '_ \/ -_) ' \ | |/ _` | '_\ V /| (_-< ",
    r"  ╲ ╰───╯ ╱     \___/| .__/\___|_||_||_|\__,_|_|  \_/ |_/__/ ",
    r"   ╰─────╯           |_|     Private AI on your machine     ",
)


def print_banner(quiet: bool = False) -> None:
    """Print the OpenJarvis startup banner. No-op when quiet."""
    if quiet:
        return
    try:
        from rich.console import Console

        console = Console()
        for line in _BANNER_LINES:
            console.print(line, highlight=False)
        console.print()
    except ImportError:
        for line in _PLAIN_BANNER:
            print(line)
        print()
