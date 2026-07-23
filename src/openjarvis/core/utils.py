"""Small cross-platform utilities used by the CLI, OAuth flow, and evals.

Kept dependency-free so importing this module is cheap (the public re-export
from ``openjarvis.core`` must not pull in heavy modules at package init).
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import time
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


def process_alive(pid: int | None) -> bool:
    """Return ``True`` if a process with *pid* is currently running.

    Cross-platform and *non-destructive*. The common POSIX idiom
    ``os.kill(pid, 0)`` must NOT be used on Windows: there ``os.kill`` maps any
    signal to ``TerminateProcess``, so a "liveness probe" would actually kill
    the process. On Windows we query ``tasklist`` instead.
    """
    if not pid or pid <= 0:
        return False
    if platform.system() == "Windows":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            check=False,
        )
        # A match prints a CSV row containing the quoted PID; "no tasks" does not.
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_process(pid: int | None, *, grace_seconds: float = 3.0) -> None:
    """Terminate *pid* gracefully, escalating to a forced kill (cross-platform).

    POSIX sends ``SIGTERM`` then, after *grace_seconds*, ``SIGKILL``. Windows
    has neither; it uses ``taskkill`` (graceful) then ``taskkill /F /T`` (force,
    whole tree). ``signal.SIGKILL`` does not exist on Windows, so it is only
    referenced inside the POSIX branch.
    """
    if not process_alive(pid):
        return
    is_windows = platform.system() == "Windows"

    if is_windows:
        subprocess.run(
            ["taskkill", "/PID", str(pid)], capture_output=True, check=False
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return
        time.sleep(0.05)

    if is_windows:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


__all__ = [
    "get_python_executable",
    "open_browser",
    "process_alive",
    "terminate_process",
]
