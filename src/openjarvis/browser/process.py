"""Owned browser process, temporary profile, port, and health management."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from openjarvis.browser.models import (
    BrowserControlHealth,
    BrowserSession,
    BrowserSessionStatus,
    utc_now,
)


class BrowserOpenError(RuntimeError):
    pass


class BrowserProfilePolicy:
    """Create and remove only marked profiles below one temporary root."""

    def __init__(self, temporary_root: str | Path) -> None:
        self.temporary_root = Path(temporary_root).resolve(strict=False)
        self.temporary_root.mkdir(parents=True, exist_ok=True)

    def create(self, session_id: str) -> Path:
        profile = Path(
            tempfile.mkdtemp(
                prefix=f"openjarvis-{session_id[:16]}-",
                dir=self.temporary_root,
            )
        ).resolve(strict=True)
        (profile / ".openjarvis-browser-profile.json").write_text(
            json.dumps({"session_id": session_id, "profile": str(profile)}),
            encoding="utf-8",
        )
        return profile

    def validate_owned(self, profile: str | Path, session_id: str) -> Path:
        path = Path(profile).resolve(strict=True)
        try:
            path.relative_to(self.temporary_root)
        except ValueError as exc:
            raise BrowserOpenError("browser profile escaped temporary root") from exc
        marker = path / ".openjarvis-browser-profile.json"
        if not marker.is_file():
            raise BrowserOpenError("browser profile is not OpenJarvis-owned")
        try:
            record = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrowserOpenError("browser profile marker is invalid") from exc
        if record.get("session_id") != session_id or record.get("profile") != str(path):
            raise BrowserOpenError("browser profile ownership mismatch")
        return path

    def remove(self, profile: str | Path, session_id: str) -> None:
        path = self.validate_owned(profile, session_id)
        last_error: OSError | None = None
        for _attempt in range(20):
            try:
                shutil.rmtree(path)
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)
        raise BrowserOpenError(
            f"owned browser profile remained locked: {type(last_error).__name__}"
        ) from last_error


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _pid_exists(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _port_owner_pid(port: int) -> int | None:
    if os.name == "nt":
        netstat = shutil.which("netstat.exe") or shutil.which("netstat")
        if not netstat:
            return None
        try:
            output = subprocess.run(
                [netstat, "-ano", "-p", "tcp"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                shell=False,
            ).stdout
        except subprocess.SubprocessError:
            return None
        suffix = f":{port}"
        candidate: int | None = None
        for line in output.splitlines():
            columns = line.split()
            if len(columns) < 5:
                continue
            local, remote, pid = columns[1], columns[2], columns[-1]
            if not local.endswith(suffix) or not pid.isdigit():
                continue
            candidate = int(pid)
            # The state label is localized on Windows.  A wildcard/zero
            # remote endpoint identifies the listening row without relying
            # on the English word "LISTENING".
            if remote.endswith(":0") or remote.endswith(":*"):
                return candidate
        return candidate
    return None


def _is_descendant_process(pid: int, root_pid: int) -> bool:
    if pid == root_pid:
        return True
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return False
    parents: dict[int, int] = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    seen: set[int] = set()
    current = pid
    while current and current not in seen:
        if current == root_pid:
            return True
        seen.add(current)
        current = parents.get(current, 0)
    return False


def _probe_health(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return isinstance(payload, dict) and bool(
        payload.get("webSocketDebuggerUrl") or payload.get("Browser")
    )


class BrowserProcessManager:
    """Start, monitor, and stop only processes created by this manager."""

    def __init__(
        self,
        *,
        executable: str | Path,
        profile_policy: BrowserProfilePolicy,
        visible: bool = False,
        command_builder: Callable[[Path, int, bool], list[str]] | None = None,
        control_restart: Callable[[BrowserSession], bool] | None = None,
    ) -> None:
        self.executable = Path(executable).resolve(strict=True)
        self.profile_policy = profile_policy
        self.visible = visible
        self.command_builder = command_builder or self._chromium_command
        self.control_restart = control_restart
        self._processes: dict[str, subprocess.Popen[bytes]] = {}

    def create_session(self) -> BrowserSession:
        session = BrowserSession(
            profile_path=Path(), control_port=_reserve_loopback_port()
        )
        session.profile_path = self.profile_policy.create(session.session_id)
        return session

    def start(
        self, session: BrowserSession, *, timeout: float = 15.0
    ) -> BrowserSession:
        existing = self._processes.get(session.session_id)
        if existing is not None and existing.poll() is None:
            session.browser_pid = existing.pid
            session.status = BrowserSessionStatus.READY
            return session
        self.profile_policy.validate_owned(session.profile_path, session.session_id)
        command = self.command_builder(
            session.profile_path,
            session.control_port,
            self.visible,
        )
        if not command or Path(command[0]).resolve(strict=True) != self.executable:
            raise BrowserOpenError("command builder changed the trusted executable")
        creationflags = (
            subprocess.CREATE_NO_WINDOW if os.name == "nt" and not self.visible else 0
        )
        session.status = BrowserSessionStatus.STARTING
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        self._processes[session.session_id] = process
        session.browser_pid = process.pid
        session.control_service_pid = process.pid
        session.browser_start_time = utc_now()
        session.owned_process = True
        deadline = time.monotonic() + timeout
        last_health: BrowserControlHealth | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                session.status = BrowserSessionStatus.DEGRADED
                raise BrowserOpenError(
                    f"browser process exited with code {process.returncode}"
                )
            last_health = self.health(session)
            if last_health.healthy:
                session.status = BrowserSessionStatus.READY
                session.safe_checkpoint = "browser.ready"
                session.last_successful_heartbeat = last_health.checked_at
                return session
            time.sleep(0.1)
        session.status = BrowserSessionStatus.DEGRADED
        detail = last_health.cause if last_health else "health_not_checked"
        raise BrowserOpenError(
            f"browser control endpoint did not become healthy: {detail}"
        )

    def health(self, session: BrowserSession) -> BrowserControlHealth:
        process_present = _pid_exists(session.browser_pid)
        control_present = _pid_exists(session.control_service_pid)
        port_open = _port_is_open(session.control_port)
        owner = _port_owner_pid(session.control_port) if port_open else None
        # Port ownership can be unavailable on non-Windows test hosts.  It may
        # never be assumed on Windows when netstat reports a different PID.
        owner_matches = False
        if owner is not None:
            owner_matches = owner == session.control_service_pid or (
                session.browser_pid is not None
                and _is_descendant_process(owner, session.browser_pid)
            )
            if owner_matches:
                session.control_service_pid = owner
                control_present = _pid_exists(owner)
        elif os.name != "nt":
            owner_matches = port_open
        connection_ok = (
            port_open and owner_matches and _probe_health(session.control_port)
        )
        causes = []
        if not process_present:
            causes.append("browser_process_missing")
        if not control_present:
            causes.append("control_service_missing")
        if not port_open:
            causes.append("control_port_closed")
        elif not owner_matches:
            causes.append("control_port_wrong_owner")
        elif not connection_ok:
            causes.append("control_connection_failed")
        checked_at = utc_now()
        if connection_ok:
            session.last_successful_heartbeat = checked_at
        return BrowserControlHealth(
            session_id=session.session_id,
            browser_process_present=process_present,
            browser_pid=session.browser_pid,
            browser_start_time=session.browser_start_time,
            profile_path=str(session.profile_path),
            control_service_present=control_present,
            control_service_pid=session.control_service_pid,
            control_port=session.control_port,
            port_open=port_open,
            port_owner_pid=owner,
            port_owner_matches=owner_matches,
            health_endpoint=f"http://127.0.0.1:{session.control_port}/json/version",
            connection_ok=connection_ok,
            last_successful_heartbeat=session.last_successful_heartbeat,
            cause=",".join(causes) if causes else "healthy",
            checked_at=checked_at,
        )

    def restart_control_service(self, session: BrowserSession) -> bool:
        if self.control_restart is None:
            return False
        return bool(self.control_restart(session))

    def close(self, session: BrowserSession, *, remove_profile: bool = True) -> None:
        process = self._processes.pop(session.session_id, None)
        if process is not None and process.poll() is None:
            _terminate_owned_tree(process)
        session.status = BrowserSessionStatus.CLOSED
        session.browser_pid = None
        session.control_service_pid = None
        if remove_profile and session.profile_path.exists():
            self.profile_policy.remove(session.profile_path, session.session_id)

    def cancel_owned(self, session: BrowserSession) -> None:
        self.close(session)

    def owns_pid(self, pid: int) -> bool:
        return any(
            process.pid == pid and process.poll() is None
            for process in self._processes.values()
        )

    def list_owned_pids(self) -> tuple[int, ...]:
        return tuple(
            process.pid
            for process in self._processes.values()
            if process.poll() is None
        )

    def _chromium_command(self, profile: Path, port: int, visible: bool) -> list[str]:
        command = [
            str(self.executable),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "about:blank",
        ]
        if not visible:
            command.insert(1, "--headless=new")
        return command


def _terminate_owned_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate only a process launched by this manager and its descendants."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        _terminate_windows_tree(process.pid)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait(timeout=5)


def _terminate_windows_tree(root_pid: int) -> None:
    """Snapshot ownership first, then terminate descendants before their root."""

    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    parents: dict[int, list[int]] = {}
    if snapshot != invalid_handle:
        try:
            entry = ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while found:
                parents.setdefault(int(entry.th32ParentProcessID), []).append(
                    int(entry.th32ProcessID)
                )
                found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)

    owned: list[int] = []

    def collect(process_id: int) -> None:
        for child in parents.get(process_id, ()):
            collect(child)
        owned.append(process_id)

    collect(root_pid)
    for process_id in owned:
        handle = kernel32.OpenProcess(0x0001 | 0x00100000, False, process_id)
        if not handle:
            continue
        try:
            kernel32.TerminateProcess(handle, 1)
            kernel32.WaitForSingleObject(handle, 5000)
        finally:
            kernel32.CloseHandle(handle)


__all__ = [
    "BrowserOpenError",
    "BrowserProcessManager",
    "BrowserProfilePolicy",
]
