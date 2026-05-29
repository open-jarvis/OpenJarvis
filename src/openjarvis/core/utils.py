"""Small cross-platform utilities used by the CLI, OAuth flow, and evals.

Kept dependency-free so importing this module is cheap (the public re-export
from ``openjarvis.core`` must not pull in heavy modules at package init).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import webbrowser


def get_python_executable() -> str:
    """Return the best ``python`` interpreter name on PATH.

    Prefers ``python3`` (Linux/macOS convention); falls back to ``python``
    (Windows / some minimal Linux distros that ship only ``python``). Returns
    the literal string ``"python3"`` when neither is found, so callers still
    get a usable command that will fail with a clear "command not found"
    rather than an empty string.

    The result is a *command name or absolute path* that callers can hand to
    :mod:`subprocess` directly when ``shell=False``, and must be shell-quoted
    (:func:`shlex.quote`) before being interpolated into a ``shell=True``
    command string — paths on Windows often contain spaces.
    """
    return shutil.which("python3") or shutil.which("python") or "python3"


def open_browser(url: str) -> None:
    """Open *url* in the user's default browser, with a Windows fast-path.

    :func:`webbrowser.open` is the cross-platform default, but on Windows it
    sometimes blocks or fails inside a console host. ``cmd /c start "" "URL"``
    is the canonical Windows incantation that hands the URL to the OS shell
    and returns immediately. We try that first on Windows and fall back to
    :func:`webbrowser.open` if the subprocess spawn fails.
    """
    if platform.system() == "Windows":
        try:
            # The empty title argument after ``start`` is required: ``start``
            # treats a single quoted argument as a window title, not a URL.
            subprocess.run(["cmd", "/c", "start", "", url], check=False)
            return
        except Exception:  # noqa: BLE001 - any spawn failure -> fall back
            pass
    webbrowser.open(url)


__all__ = ["get_python_executable", "open_browser"]
