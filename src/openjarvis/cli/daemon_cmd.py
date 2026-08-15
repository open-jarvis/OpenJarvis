"""``jarvis start|stop|restart|status`` — daemon management commands."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import click
from rich.console import Console

from openjarvis.core.config import DEFAULT_CONFIG_DIR, load_config

_PID_FILE = DEFAULT_CONFIG_DIR / "server.pid"
_LOG_FILE = DEFAULT_CONFIG_DIR / "server.log"


def _pid_alive(pid: int) -> bool:
    """Return whether *pid* identifies a running process without signaling it."""
    if pid <= 0:
        return False

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        error_invalid_parameter = 87
        synchronize = 0x00100000
        wait_object_0 = 0x00000000

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            # OpenProcess reports ERROR_INVALID_PARAMETER when the PID does not
            # exist. For access-denied and other inconclusive failures, retain
            # the PID file rather than declaring a potentially live daemon dead.
            return ctypes.get_last_error() != error_invalid_parameter

        try:
            wait_result = kernel32.WaitForSingleObject(handle, 0)
            # WAIT_OBJECT_0 proves the process exited. WAIT_TIMEOUT proves it
            # is live; unexpected failures are inconclusive, so retain the PID.
            return wait_result != wait_object_0
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid() -> int | None:
    """Read PID from pid file, return None if not found or stale."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
    except (OSError, ValueError):
        _PID_FILE.unlink(missing_ok=True)
        return None
    if not _pid_alive(pid):
        _PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def _write_pid(pid: int) -> None:
    """Write PID to pid file."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


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
    _write_pid(proc.pid)

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

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait up to 10 seconds for graceful shutdown
        for _ in range(20):
            time.sleep(0.5)
            if not _pid_alive(pid):
                break
        else:
            # SIGKILL is POSIX-only. On Windows SIGTERM already maps to
            # TerminateProcess, so repeating it is the available escalation.
            try:
                os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
            except OSError:
                pass
    except OSError:
        pass

    _PID_FILE.unlink(missing_ok=True)
    console.print(f"[green]Server stopped[/green] (PID {pid}).")


@daemon.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart the OpenJarvis server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is not None:
        console.print(f"Stopping server (PID {pid})...")
        ctx.invoke(stop)
    ctx.invoke(start)


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

    config = load_config()
    console.print(
        f"[green]Server is running[/green] (PID {pid}){uptime_info}\n"
        f"  URL: http://{config.server.host}:{config.server.port}\n"
        f"  Log: {_LOG_FILE}"
    )


__all__ = ["daemon", "start", "stop", "restart", "status"]
