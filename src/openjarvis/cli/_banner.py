"""Startup banner — OpenJarvis wordmark + tagline."""

from __future__ import annotations

# "OpenJarvis" rendered in the figlet "standard" font. Stored as plain text
# (no inline Rich markup) so the backslashes in the glyphs don't collide with
# Rich's [tag] markup or Python raw-string escaping — colour is applied at
# print time via a style argument. The "standard" font renders a clearly
# readable capital J (the bottom-left \___/ hook), unlike the cramped prior
# art where the J read as an I.
_WORDMARK = (
    '  ___                       _                  _     ',
    ' / _ \\ _ __   ___ _ __     | | __ _ _ ____   _(_)___ ',
    "| | | | '_ \\ / _ \\ '_ \\ _  | |/ _` | '__\\ \\ / / / __|",
    '| |_| | |_) |  __/ | | | |_| | (_| | |   \\ V /| \\__ \\',
    ' \\___/| .__/ \\___|_| |_|\\___/ \\__,_|_|    \\_/ |_|___/',
    '      |_|                                            ',
)

_TAGLINE = "Personal AI, On Personal Devices"


def print_banner(quiet: bool = False) -> None:
    """Print the OpenJarvis startup banner. No-op when quiet."""
    if quiet:
        return
    try:
        from rich.console import Console

        console = Console()
        for line in _WORDMARK:
            console.print(line, style="bold bright_blue", highlight=False, markup=False)
        console.print(f"      {_TAGLINE}", style="cyan", highlight=False, markup=False)
        console.print()
    except ImportError:
        for line in _WORDMARK:
            print(line)
        print(f"      {_TAGLINE}")
        print()
