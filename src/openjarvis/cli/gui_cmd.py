"""``jarvis gui`` — start and open the local graphical interface."""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import click
from rich.console import Console

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.utils import process_alive, terminate_process
from openjarvis.security.file_utils import secure_write_json

# Records the frontend this command started, so a later run can tell its own
# leftover dev server apart from an unrelated application holding the port.
# ``npm run dev`` is npm -> cmd.exe -> node and only the leaf binds the port,
# so an interrupted run routinely leaves that leaf behind; see _reclaim_port.
_FRONTEND_STATE_FILE = DEFAULT_CONFIG_DIR / "frontend.json"

# How often to re-check that the API is still up while the frontend runs.
_API_POLL_SECONDS = 5.0

# How many consecutive failed probes mean the API is really gone. A single
# failure proves nothing: a loopback connect to a busy server intermittently
# stalls for seconds, and treating one timeout as death tears down a working
# GUI — a worse bug than the dead-backend one this watch exists to catch.
_API_FAILURES_BEFORE_DOWN = 3


def _frontend_dir() -> Path | None:
    """Find the source checkout's frontend directory."""
    configured = os.environ.get("OPENJARVIS_FRONTEND_DIR")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).resolve().parents[3] / "frontend")
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "package.json").is_file():
            return candidate
    return None


def _read_frontend_state() -> dict:
    """Return the recorded frontend, or {} when it is missing or malformed."""
    try:
        state = json.loads(_FRONTEND_STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    if (
        type(state.get("pid")) is not int
        or state["pid"] <= 0
        or type(state.get("port")) is not int
        or not 0 <= state["port"] <= 65535
    ):
        return {}
    return state


def record_frontend_state(pid: int, port: int) -> None:
    """Register a running frontend so a later run (or stop) can reclaim it."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    secure_write_json(_FRONTEND_STATE_FILE, {"pid": pid, "port": port})


def clear_frontend_state(pid: int) -> None:
    """Deregister a frontend, but only if it still owns the file."""
    if _read_frontend_state().get("pid") == pid:
        _FRONTEND_STATE_FILE.unlink(missing_ok=True)


def stop_frontend() -> int | None:
    """Stop the recorded frontend. Returns the PID stopped, or None."""
    state = _read_frontend_state()
    pid = state.get("pid")
    if pid is None:
        return None
    if not process_alive(pid):
        _FRONTEND_STATE_FILE.unlink(missing_ok=True)
        return None
    # Force-kills the whole tree on Windows, which is the point: the PID
    # recorded here is npm's, and the node grandchild is what holds the port.
    terminate_process(pid, grace_seconds=5.0)
    clear_frontend_state(pid)
    return pid


def _port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def _port_owner_pid(port: int) -> int | None:
    """Best-effort PID listening on *port*, for a message the user can act on."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    and parts[0].upper() == "TCP"
                    and parts[3].upper() == "LISTENING"
                    and parts[1].endswith(f":{port}")
                ):
                    return int(parts[4])
            return None
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        return int(out[0]) if out else None
    except (OSError, ValueError):
        return None


def _reclaim_port(port: int) -> bool:
    """Free *port* when this command's own earlier frontend still holds it.

    A frontend killed outright (console close, taskkill, a crashed terminal)
    never runs its cleanup, so the recorded PID is the only reliable way to
    tell "my own orphan, safe to kill" from "someone else's server".
    """
    if _read_frontend_state().get("port") != port:
        return False
    if stop_frontend() is None:
        return _port_free(port)
    for _ in range(20):
        if _port_free(port):
            return True
        time.sleep(0.25)
    return False


def _check_frontend_port(port: int) -> None:
    """Reject a port already bound by another local application."""
    if _port_free(port):
        return
    if _reclaim_port(port):
        return
    owner = _port_owner_pid(port)
    held_by = f" It is held by PID {owner}." if owner else ""
    raise click.ClickException(
        f"Frontend port {port} is unavailable and was not started by "
        f"OpenJarvis.{held_by} Stop it, or choose another port with "
        f"--frontend-port."
    )


def _api_healthy(port: int, timeout: float = 3.0) -> bool:
    """Return whether an API server is answering on *port*."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=timeout
        ) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _daemon_pid_alive(port: int) -> bool:
    """Whether the daemon registered on *port* is still a live process.

    Corroborates a run of failed health probes: a wedged-but-running server
    should not be reported as stopped, and only the daemon's own bookkeeping
    knows which process is supposed to be serving this port.
    """
    # Imported lazily; daemon_cmd imports this module for its own `stop`.
    from openjarvis.cli.daemon_cmd import _read_state

    state = _read_state()
    if state.get("port") != port:
        return False
    return process_alive(state["pid"])


def _wait_for_port(
    process: subprocess.Popen[bytes], host: str, port: int, timeout: float = 20.0
) -> bool:
    """Wait for this launch's frontend process to listen on the requested port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return process.poll() is None
        except OSError:
            time.sleep(0.2)
    return False


def _ensure_frontend_dependencies(frontend: Path, npm: str) -> None:
    """Install frontend dependencies when this checkout has not been bootstrapped."""
    vite = (
        frontend
        / "node_modules"
        / ".bin"
        / ("vite.cmd" if sys.platform == "win32" else "vite")
    )
    if vite.exists():
        return
    click.echo("Installing graphical frontend dependencies...", err=True)
    result = subprocess.run(
        [npm, "install", "--no-audit", "--no-fund"],
        cwd=frontend,
        check=False,
    )
    if result.returncode != 0:
        raise click.ClickException(
            "Could not install frontend dependencies. "
            "Run `npm install` in the frontend directory."
        )


@click.command()
@click.option(
    "--frontend-port", default=5173, show_default=True, type=click.IntRange(1, 65535)
)
@click.option(
    "--api-port", default=8000, show_default=True, type=click.IntRange(1, 65535)
)
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
            "Download the OpenJarvis desktop app or run this command "
            "from a source checkout."
        )
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        raise click.ClickException(
            "Node.js/npm is required for graphical mode. Install Node.js 22 or newer."
        )
    _check_frontend_port(frontend_port)
    _ensure_frontend_dependencies(frontend, npm)

    # `jarvis start` exits non-zero when a daemon is already registered, so
    # without this a perfectly healthy API turned into the misleading "Could
    # not start the OpenJarvis API server." Adopt it instead.
    if not no_server and _api_healthy(api_port):
        console.print(
            f"[green]Reusing the API server already running "
            f"on port {api_port}.[/green]"
        )
        no_server = True

    if not no_server:
        uv = shutil.which("uv")
        if uv is None:
            raise click.ClickException(
                "uv is required to start the API with desktop dependencies. "
                "Install uv or use --no-server with an already-running API."
            )
        server = subprocess.run(
            [
                uv,
                "run",
                "--extra",
                "desktop",
                "jarvis",
                "start",
                "--port",
                str(api_port),
            ],
            cwd=frontend.parent,
            check=False,
        )
        if server.returncode != 0:
            raise click.ClickException("Could not start the OpenJarvis API server.")

    env = os.environ.copy()
    # Let browser requests use Vite's same-origin proxy at any frontend port.
    # VITE_API_URL is exposed to browser code, so clear an inherited override.
    env["VITE_API_URL"] = ""
    env["OPENJARVIS_VITE_PROXY_TARGET"] = f"http://127.0.0.1:{api_port}"
    process = subprocess.Popen(
        [
            npm,
            "run",
            "dev",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(frontend_port),
            "--strictPort",
        ],
        cwd=frontend,
        env=env,
    )

    def shutdown_frontend() -> None:
        # Never process.terminate() here: that reaps npm and leaves the node
        # grandchild holding the port, which is what made the next run fail
        # with "Frontend port is unavailable".
        terminate_process(process.pid, grace_seconds=5.0)
        clear_frontend_state(process.pid)

    atexit.register(shutdown_frontend)
    # Ctrl-C arrives as KeyboardInterrupt below, but a console-close or a
    # taskkill does not. Exiting from the handler lets atexit still run.
    for signum in (signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if signum is not None:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(signum, lambda *_: sys.exit(1))

    if not _wait_for_port(process, "127.0.0.1", frontend_port):
        shutdown_frontend()
        raise click.ClickException(
            "The graphical frontend did not start on the requested port."
        )
    record_frontend_state(process.pid, frontend_port)

    url = f"http://127.0.0.1:{frontend_port}"
    console.print(f"[green]OpenJarvis graphical mode is ready:[/green] {url}")
    if not no_browser:
        webbrowser.open(url)

    # Watch whatever API we expect to be there, however it got started. A
    # frontend left running against a dead API looks like a working app but
    # fails every request, which is the confusing symptom this avoids.
    watch_api = _api_healthy(api_port)
    failures = 0
    try:
        while True:
            try:
                process.wait(timeout=_API_POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                pass
            if not watch_api:
                continue
            if _api_healthy(api_port):
                failures = 0
                continue
            failures += 1
            if failures < _API_FAILURES_BEFORE_DOWN or _daemon_pid_alive(api_port):
                continue
            console.print(
                "[red]The API server stopped; shutting down the frontend.[/red]\n"
                f"  Check {DEFAULT_CONFIG_DIR / 'server.log'}, "
                f"then run 'jarvis gui' again."
            )
            raise SystemExit(1)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_frontend()
