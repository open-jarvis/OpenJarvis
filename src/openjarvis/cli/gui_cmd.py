"""``jarvis gui`` — start and open the local graphical interface."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import click
from rich.console import Console


def _frontend_dir() -> Path | None:
    """Find the source checkout's frontend directory."""
    configured = os.environ.get("OPENJARVIS_FRONTEND_DIR")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).resolve().parents[3] / "frontend")
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "package.json").is_file():
            return candidate
    return None


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


@click.command()
@click.option("--frontend-port", default=5173, show_default=True, type=int)
@click.option("--api-port", default=8000, show_default=True, type=int)
@click.option("--no-server", is_flag=True, help="Do not start the API server.")
@click.option("--no-browser", is_flag=True, help="Only start the frontend.")
def gui(frontend_port: int, api_port: int, no_server: bool, no_browser: bool) -> None:
    """Start the browser-based graphical mode in the default browser.

    This command is intended for source checkouts. For an installed desktop
    application, launch OpenJarvis from the operating system menu instead.
    """
    console = Console(stderr=True)
    frontend = _frontend_dir()
    if frontend is None:
        raise click.ClickException(
            "The graphical frontend is not available in this installation. "
            "Download the OpenJarvis desktop app or run this command from a source checkout."
        )
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        raise click.ClickException(
            "Node.js/npm is required for graphical mode. Install Node.js 22 or newer."
        )

    if not no_server:
        server = subprocess.run(
            [sys.executable, "-m", "openjarvis.cli", "start", "--port", str(api_port)],
            check=False,
        )
        if server.returncode != 0:
            raise click.ClickException("Could not start the OpenJarvis API server.")

    env = os.environ.copy()
    env["VITE_API_URL"] = f"http://127.0.0.1:{api_port}"
    process = subprocess.Popen(
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(frontend_port)],
        cwd=frontend,
        env=env,
    )
    if not _wait_for_port("127.0.0.1", frontend_port):
        process.terminate()
        raise click.ClickException("The graphical frontend did not start in time.")

    url = f"http://127.0.0.1:{frontend_port}"
    console.print(f"[green]OpenJarvis graphical mode is ready:[/green] {url}")
    if not no_browser:
        webbrowser.open(url)
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()

