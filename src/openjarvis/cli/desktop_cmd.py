"""``jarvis desktop`` — open the OpenJarvis UI in a native app window.

Wraps the existing web frontend (already served by ``jarvis serve`` — see
``server/app.py``'s static-file mount) in a native OS window via
``pywebview``, instead of the user opening a browser tab at localhost. No
address bar, no tabs, no browser chrome — just a titled, iconed application
window. The frontend itself is untouched; this only changes how it's
displayed.

Chosen over completing the existing (partial, uncompiled) Tauri desktop app
in ``frontend/src-tauri/``: that would require installing the full Rust +
MSVC build toolchain, a heavy one-time setup with real risk of platform-
specific build issues. ``pywebview`` needs only a single lightweight Python
package (using the OS's already-installed WebView2 runtime on Windows) and
fully satisfies the requirement — a native window with no browser
controls around the same running web UI — without rebuilding anything.
"""

from __future__ import annotations

import atexit
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

logger = logging.getLogger(__name__)

_WINDOW_TITLE = "OpenJarvis (J.A.R.V.I.S.)"
_STARTUP_TIMEOUT_S = 60.0
_POLL_INTERVAL_S = 0.5

# The Tauri app's icon is already a committed repo asset — reuse it rather
# than duplicating an icon file. Falls back to no icon (pywebview's default)
# if this is ever run from an install that doesn't carry the frontend/
# source tree (e.g. a built wheel), rather than crashing.
_ICON_PATH = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src-tauri"
    / "icons"
    / "icon.ico"
)


def _resolve_icon() -> Optional[str]:
    return str(_ICON_PATH) if _ICON_PATH.is_file() else None


def _start_server(host: str, port: Optional[int]) -> subprocess.Popen:
    """Spawn ``jarvis serve`` as a plain (non-detached) child process.

    Not detached (unlike ``jarvis start``'s daemon spawn in
    ``cli/daemon_cmd.py``) — this process's lifecycle must stay tied to the
    window so it can be terminated cleanly when the window closes.
    """
    cmd = [sys.executable, "-m", "openjarvis.cli", "serve", "--host", host]
    if port:
        cmd.extend(["--port", str(port)])
    return subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user input
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_until_healthy(url: str, timeout_s: float) -> bool:
    import requests

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(_POLL_INTERVAL_S)
    return False


def _stop_server(proc: subprocess.Popen, timeout_s: float = 5.0) -> None:
    """Terminate the server process, escalating to a kill if it won't exit."""
    if proc.poll() is not None:
        return  # already exited
    try:
        proc.terminate()
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            logger.warning("jarvis serve (pid %s) did not exit after kill()", proc.pid)
    except Exception:  # noqa: BLE001 - never let cleanup crash on the way out
        logger.debug("Error stopping jarvis serve subprocess", exc_info=True)


@click.command(
    "desktop", help="Open the OpenJarvis UI in a native app window (no browser)."
)
@click.option("--host", default="127.0.0.1", help="Backend bind address.")
@click.option("--port", default=None, type=int, help="Backend port (default: config).")
@click.option("--width", default=1280, type=int, help="Initial window width.")
@click.option("--height", default=800, type=int, help="Initial window height.")
def desktop(host: str, port: Optional[int], width: int, height: int) -> None:
    """Start the backend (if needed) and show the UI in a native window."""
    console = Console()

    try:
        import webview
    except ImportError:
        console.print(
            "[red bold]pywebview is not installed.[/red bold]\n\n"
            "Install it with:\n"
            "  [cyan]uv sync --extra desktop-window[/cyan]"
        )
        sys.exit(1)

    from openjarvis.core.config import load_config

    config = load_config()
    resolved_port = port or config.server.port or 8000
    url = f"http://{host}:{resolved_port}"

    console.print(f"[cyan]Starting OpenJarvis backend on {url}...[/cyan]")
    proc = _start_server(host, port)
    atexit.register(_stop_server, proc)

    if not _wait_until_healthy(url, _STARTUP_TIMEOUT_S):
        console.print(
            f"[red bold]Backend did not become healthy within "
            f"{_STARTUP_TIMEOUT_S:.0f}s.[/red bold] Check the logs and try again."
        )
        _stop_server(proc)
        sys.exit(1)

    console.print("[green]Opening window...[/green]")
    webview.create_window(
        _WINDOW_TITLE,
        url,
        width=width,
        height=height,
        min_size=(800, 600),
    )
    try:
        webview.start(icon=_resolve_icon())
    finally:
        # webview.start() blocks until every window is closed; always stop
        # the backend on the way out so no process is left running.
        _stop_server(proc)


__all__ = ["desktop"]
