"""``jarvis start|stop|restart|status`` — daemon management commands."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import click
from rich.console import Console

from openjarvis.core.config import DEFAULT_CONFIG_DIR, load_config
from openjarvis.core.utils import process_alive, terminate_process

_PID_FILE = DEFAULT_CONFIG_DIR / "server.pid"
_LOG_FILE = DEFAULT_CONFIG_DIR / "server.log"
# Records the address the daemon was actually started on. Without it `status`
# and `restart` fall back to the config defaults and misreport (or silently
# move) the port whenever `start` was given an explicit --host/--port.
_STATE_FILE = DEFAULT_CONFIG_DIR / "server.json"


def _pid_alive(pid: int) -> bool:
    """Return whether *pid* identifies a running process without signaling it."""
    return process_alive(pid)


def _read_pid() -> int | None:
    """Read PID from pid file, return None if not found or stale."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
    except (OSError, ValueError):
        _PID_FILE.unlink(missing_ok=True)
        return None
    # Check if process is still running (non-destructive, cross-platform).
    if not _pid_alive(pid):
        _PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def _write_pid(pid: int, host: str = "", port: int | None = None) -> None:
    """Write PID, plus the address the daemon actually bound to."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))
    if host or port is not None:
        _STATE_FILE.write_text(json.dumps({"pid": pid, "host": host, "port": port}))


def _read_state() -> dict:
    """Return the recorded daemon address, or {} when it is unavailable."""
    try:
        state = json.loads(_STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _bound_address() -> tuple[str, int]:
    """Resolve the daemon's address, preferring what `start` recorded."""
    config = load_config()
    state = _read_state()
    host = state.get("host") or config.server.host
    port = state.get("port") or config.server.port
    return host, int(port)


def record_server_state(pid: int, host: str, port: int) -> None:
    """Register a running server so `jarvis status` can find it.

    Called by `jarvis serve` itself, so a server supervised by launchd/systemd
    (which never goes through `jarvis start`) is still reported as running.
    """
    _write_pid(pid, host, port)


def clear_server_state(pid: int) -> None:
    """Deregister a server on shutdown, but only if it still owns the files."""
    if _read_state().get("pid") == pid or _read_pid() == pid:
        _PID_FILE.unlink(missing_ok=True)
        _STATE_FILE.unlink(missing_ok=True)


@click.group()
def daemon() -> None:
    """Manage the OpenJarvis server daemon."""


@daemon.command()
@click.option("--host", default=None, help="Bind address.")
@click.option("--port", default=None, type=int, help="Port number.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
def start(
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
) -> None:
    """Start the OpenJarvis server as a background daemon."""
    console = Console(stderr=True)

    existing = _read_pid()
    if existing is not None:
        console.print(f"[yellow]Server already running (PID {existing}).[/yellow]")
        console.print("Use 'jarvis stop' to stop it first, or 'jarvis restart'.")
        sys.exit(1)

    config = load_config()
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Build command to run jarvis serve
    cmd = [sys.executable, "-m", "openjarvis.cli", "serve"]
    if host:
        cmd.extend(["--host", host])
    if port:
        cmd.extend(["--port", str(port)])
    if engine_key:
        cmd.extend(["--engine", engine_key])
    if model_name:
        cmd.extend(["--model", model_name])
    if agent_name:
        cmd.extend(["--agent", agent_name])

    # Start as background process, fully detached from the launching terminal.
    #
    # ``start_new_session`` is POSIX-only: CPython's Windows ``_execute_child``
    # names the parameter ``unused_start_new_session`` and ignores it. Relying
    # on it there leaves the server sharing its parent's console, so closing
    # that console — or logging off — delivers CTRL_CLOSE_EVENT and kills the
    # daemon. DETACHED_PROCESS gives it no console at all; the new process
    # group additionally stops a Ctrl-C in the parent reaching it.
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = open(_LOG_FILE, "a")  # noqa: SIM115
    spawn_kwargs: dict = {}
    if sys.platform == "win32":
        spawn_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        spawn_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=log_fh,
        **spawn_kwargs,
    )
    _write_pid(proc.pid, bind_host, bind_port)

    console.print(
        f"[green]OpenJarvis server started[/green] (PID {proc.pid})\n"
        f"  URL: http://{bind_host}:{bind_port}\n"
        f"  Log: {_LOG_FILE}"
    )


@daemon.command()
def stop() -> None:
    """Stop the running OpenJarvis server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]No running server found.[/yellow]")
        sys.exit(1)

    # Graceful shutdown (SIGTERM / taskkill), escalating to a forced kill after
    # 10s if still running. Cross-platform — no POSIX-only os.kill/SIGKILL.
    terminate_process(pid, grace_seconds=10.0)

    _PID_FILE.unlink(missing_ok=True)
    _STATE_FILE.unlink(missing_ok=True)
    console.print(f"[green]Server stopped[/green] (PID {pid}).")


@daemon.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart the OpenJarvis server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    previous = _read_state() if pid is not None else {}
    if pid is not None:
        console.print(f"Stopping server (PID {pid})...")
        ctx.invoke(stop)
    # Carry the previous bind address across the restart; otherwise an explicit
    # `start --port N` silently reverts to the config default on restart.
    ctx.invoke(
        start,
        host=previous.get("host") or None,
        port=previous.get("port") or None,
    )


@daemon.command()
def status() -> None:
    """Show status of the OpenJarvis server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]Server is not running.[/yellow]")
        return

    # Get process info
    uptime_info = ""
    try:
        import psutil

        proc = psutil.Process(pid)
        uptime = time.time() - proc.create_time()
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_info = f"\n  Uptime: {hours}h {minutes}m {seconds}s"
    except (ImportError, Exception):
        pass

    host, port = _bound_address()
    console.print(
        f"[green]Server is running[/green] (PID {pid}){uptime_info}\n"
        f"  URL: http://{host}:{port}\n"
        f"  Log: {_LOG_FILE}"
    )


__all__ = ["daemon", "start", "stop", "restart", "status"]
