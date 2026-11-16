"""``jarvis gui`` — start and open the local graphical interface."""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import secrets
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
import psutil
from rich.console import Console

from openjarvis.core.config import DEFAULT_CONFIG_DIR
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


def _frontend_state_lock():
    from openjarvis.cli.daemon_cmd import _state_lock

    return _state_lock(_FRONTEND_STATE_FILE)


def clear_frontend_state(pid: int, launch_token: str | None) -> None:
    """Deregister a frontend, but only if it still owns the file."""
    with _frontend_state_lock():
        state = _read_frontend_state()
        if state.get("pid") == pid and state.get("launch_token") == launch_token:
            _FRONTEND_STATE_FILE.unlink(missing_ok=True)


def _process_identity(process: psutil.Process) -> dict | None:
    """Return an identity that cannot be confused with a recycled PID."""
    if sys.platform == "linux":
        from openjarvis.cli.daemon_cmd import _linux_process_identity

        # psutil's Linux epoch start time depends on the current boot epoch.
        # Keep the same clock-stable identity used by daemon bookkeeping.
        return _linux_process_identity(process.pid)
    return {"pid": process.pid, "created_at": process.create_time()}


def _inspect_frontend_processes(state: dict) -> tuple[list[psutil.Process], list[dict]]:
    """Separate verified owners from records whose identity is temporarily unknown."""
    if not isinstance(state.get("launch_token"), str) or not state["launch_token"]:
        return [], []
    records = state.get("processes")
    if not isinstance(records, list):
        return [], []
    owned, unknown = [], []
    for record in records:
        if not isinstance(record, dict) or type(record.get("pid")) is not int:
            continue
        if record["pid"] <= 0 or not isinstance(record.get("identity"), dict):
            continue
        try:
            process = psutil.Process(record["pid"])
            identity = _process_identity(process)
            if identity is None:
                unknown.append(record)
            elif (
                identity == record["identity"]
                and process.status() != psutil.STATUS_ZOMBIE
            ):
                # The Linux identity already checks start ticks and boot ID;
                # an epoch-based psutil comparison can change with the clock.
                if sys.platform != "linux" and not process.is_running():
                    continue
                owned.append(process)
        except psutil.NoSuchProcess:
            continue
        except (psutil.Error, OSError):
            unknown.append(record)
        except (ValueError, OverflowError):
            continue
    return owned, unknown


def _owned_processes(state: dict) -> list[psutil.Process]:
    """Recover only verified identities; a bare legacy PID is not ownership."""
    return _inspect_frontend_processes(state)[0]


def _frontend_processes(
    state: dict,
    live_process: subprocess.Popen | None = None,
    *,
    verified: list[psutil.Process] | None = None,
) -> list[psutil.Process]:
    """Include current descendants of verified owners and the live child we own."""
    owners = _owned_processes(state) if verified is None else verified
    processes = {process.pid: process for process in owners}
    if live_process is not None and live_process.poll() is None:
        try:
            # A live, unreaped Popen child belongs to this invocation. This
            # path also lets startup failure clean up before state is saved.
            processes[live_process.pid] = psutil.Process(live_process.pid)
        except psutil.Error:
            pass
    for process in list(processes.values()):
        try:
            for child in process.children(recursive=True):
                processes[child.pid] = child
        except psutil.Error:
            continue
    return list(processes.values())


def _terminate_frontend(
    state: dict, live_process: subprocess.Popen | None = None
) -> bool:
    owned, unknown = _inspect_frontend_processes(state)
    if unknown:
        raise click.ClickException(
            "Could not verify frontend process ownership; saved state was kept. "
            "Retry when process information is accessible."
        )
    processes = _frontend_processes(state, live_process, verified=owned)
    # POSIX launchers have a dedicated session. A verified surviving member
    # proves the group still belongs to this launch even after npm has exited.
    group = state.get("process_group")
    if os.name != "nt" and type(group) is int and group == state.get("pid"):
        for process in processes:
            try:
                if os.getpgid(process.pid) == group and process.is_running():
                    os.killpg(group, signal.SIGTERM)
                    break
            except (OSError, psutil.Error):
                continue
    for process in reversed(processes):
        with contextlib.suppress(psutil.Error):
            process.terminate()
    _, alive = psutil.wait_procs(processes, timeout=5.0)
    for process in alive:
        with contextlib.suppress(psutil.Error):
            process.kill()
    _, remaining = psutil.wait_procs(alive, timeout=1.0)
    if remaining:
        raise click.ClickException("Could not stop every owned frontend process.")
    if live_process is not None and live_process.poll() is None:
        live_process.terminate()
        try:
            live_process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            live_process.kill()
            live_process.wait(timeout=1.0)
    remaining_owned, unknown = _inspect_frontend_processes(state)
    if remaining_owned or unknown:
        raise click.ClickException(
            "Frontend ownership could not be cleared safely; saved state was kept."
        )
    return bool(processes)


class _FrontendOwner:
    """Track a launch's process identities without leaving stale exit hooks."""

    def __init__(self, process: subprocess.Popen, port: int) -> None:
        self.process = process
        self.state = {
            "pid": process.pid,
            "port": port,
            "launch_token": secrets.token_hex(16),
            "processes": [],
            "process_group": process.pid if os.name != "nt" else None,
        }
        self.registered = False
        self.closed = False

    def refresh(self) -> None:
        previous = {record["pid"]: record for record in self.state["processes"]}
        # A denied/transient read is not evidence that a process ended. Keep
        # its last verified identity so a later stop/reclaim can retry safely.
        owned, unknown = _inspect_frontend_processes(self.state)
        records = {record["pid"]: record for record in unknown}
        for process in _frontend_processes(self.state, self.process, verified=owned):
            try:
                identity = _process_identity(process)
                if process.pid in previous:
                    # Never replace a recorded identity with a newer process
                    # that recycled this PID during refresh.
                    if (
                        identity is None
                        or identity == previous[process.pid]["identity"]
                    ):
                        records[process.pid] = previous[process.pid]
                elif identity is not None and process.is_running():
                    confirmed = _process_identity(process)
                    if confirmed == identity:
                        records[process.pid] = {
                            "pid": process.pid,
                            "identity": identity,
                        }
            except psutil.NoSuchProcess:
                continue
            except (psutil.Error, OSError):
                if process.pid in previous:
                    records[process.pid] = previous[process.pid]
        updated = list(records.values())
        if updated == self.state["processes"]:
            return
        self.state["processes"] = updated
        if self.registered:
            with _frontend_state_lock():
                current = _read_frontend_state()
                if current.get("pid") == self.state["pid"] and (
                    current.get("launch_token") == self.state["launch_token"]
                ):
                    secure_write_json(_FRONTEND_STATE_FILE, self.state)

    def register(self) -> None:
        self.refresh()
        if not any(
            record["pid"] == self.process.pid for record in self.state["processes"]
        ):
            raise click.ClickException(
                "Could not verify the frontend process identity."
            )
        with _frontend_state_lock():
            current = _read_frontend_state()
            if current.get("launch_token") != self.state["launch_token"]:
                owned, unknown = _inspect_frontend_processes(current)
                if owned or unknown:
                    raise click.ClickException(
                        "Another frontend is still registered. Stop that graphical "
                        "session before starting a new one."
                    )
            secure_write_json(_FRONTEND_STATE_FILE, self.state)
        self.registered = True

    def shutdown(self) -> None:
        if self.closed:
            return
        self.closed = True
        _terminate_frontend(self.state, self.process)
        clear_frontend_state(self.state["pid"], self.state["launch_token"])


def stop_frontend(*, state: dict | None = None) -> int | None:
    """Stop the recorded frontend, optionally using a port check's exact snapshot.

    Unknown ownership keeps the saved state and raises so a later call can
    retry. Returns the launch PID stopped, or None for a stale registration.
    """
    state = _read_frontend_state() if state is None else state
    pid = state.get("pid")
    if pid is None:
        return None
    stopped = _terminate_frontend(state)
    clear_frontend_state(pid, state.get("launch_token"))
    return pid if stopped else None


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

    A frontend killed outright never runs its cleanup. Saved process
    identities identify verified survivors of our earlier launch; a bare PID
    does not establish ownership after the operating system reuses it.
    """
    state = _read_frontend_state()
    if state.get("port") != port:
        return False
    if stop_frontend(state=state) is None:
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


def _daemon_pid_alive(port: int, *, require_ready: bool = False) -> bool:
    """Whether the daemon registered on *port* is still a live process.

    Corroborates a run of failed health probes: a wedged-but-running server
    should not be reported as stopped, and only the daemon's own bookkeeping
    knows which process is supposed to be serving this port.
    """
    # Imported lazily; daemon_cmd imports this module for its own `stop`.
    from openjarvis.cli.daemon_cmd import _read_pid_unlocked, _read_state, _state_lock

    with _state_lock():
        state = _read_state()
        if state.get("port") != port or (require_ready and state.get("ready") is False):
            return False
        return _read_pid_unlocked() == state["pid"]


def _wait_for_port(
    process: subprocess.Popen[bytes],
    host: str,
    port: int,
    timeout: float = 20.0,
    *,
    on_poll=None,
) -> bool:
    """Wait for this launch's frontend process to listen on the requested port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if on_poll is not None:
            on_poll()
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
        if not _daemon_pid_alive(api_port, require_ready=True):
            raise click.ClickException(
                f"API port {api_port} is already serving an unregistered service. "
                "Stop it or choose another port. Use --no-server only when you "
                "intend to use an externally managed OpenJarvis backend."
            )
        console.print(
            f"[green]Reusing the API server already running on port {api_port}.[/green]"
        )
        no_server = True

    launched_api = not no_server
    if launched_api:
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
    spawn_kwargs = {}
    if sys.platform == "win32":
        spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        spawn_kwargs["start_new_session"] = True
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
        **spawn_kwargs,
    )
    owner = _FrontendOwner(process, frontend_port)
    shutdown = owner.shutdown
    handlers = {}
    atexit.register(shutdown)
    try:
        for signum in (signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
            if signum is not None:
                with contextlib.suppress(OSError, ValueError):
                    previous = signal.getsignal(signum)
                    signal.signal(signum, lambda *_: sys.exit(1))
                    handlers[signum] = previous
        owner.register()
        if not _wait_for_port(
            process, "127.0.0.1", frontend_port, on_poll=owner.refresh
        ):
            raise click.ClickException(
                "The graphical frontend did not start on the requested port."
            )
        owner.refresh()
        url = f"http://127.0.0.1:{frontend_port}"
        console.print(f"[green]OpenJarvis graphical mode is ready:[/green] {url}")
        if not no_browser:
            webbrowser.open(url)

        watch_api = _api_healthy(api_port)
        failures = 0
        while True:
            owner.refresh()
            try:
                process.wait(timeout=_API_POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                pass
            healthy = _api_healthy(api_port)
            if healthy:
                watch_api = True
                failures = 0
                continue
            if not watch_api and not launched_api:
                continue
            failures += 1
            if failures < _API_FAILURES_BEFORE_DOWN or _daemon_pid_alive(api_port):
                continue
            console.print(
                "[red]The API server stopped or failed to start; "
                "shutting down the frontend.[/red]\n"
                f"  Check {DEFAULT_CONFIG_DIR / 'server.log'}, "
                f"then run 'jarvis gui' again."
            )
            raise SystemExit(1)
    except KeyboardInterrupt:
        pass
    finally:
        atexit.unregister(shutdown)
        for signum, previous in handlers.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(signum, previous)
        shutdown()
