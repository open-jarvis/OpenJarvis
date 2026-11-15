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
import sys
import time
import webbrowser


def _windows_process_alive(pid: int) -> bool:
    """Query a Windows process handle without sending it a signal."""
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
        # ERROR_INVALID_PARAMETER proves that the PID does not exist. Access
        # denied is inconclusive, so do not treat a potentially live process as
        # dead and risk starting a duplicate daemon.
        return ctypes.get_last_error() != error_invalid_parameter

    try:
        # WAIT_OBJECT_0 means the process handle is signaled (the process has
        # exited). WAIT_TIMEOUT and unexpected failures are conservatively live.
        return kernel32.WaitForSingleObject(handle, 0) != wait_object_0
    finally:
        kernel32.CloseHandle(handle)


def _posix_process_state(pid: int) -> str | None:
    """Return a POSIX process state letter, or ``None`` when unavailable."""
    proc_root = "/proc"
    try:
        with open(f"{proc_root}/{pid}/stat", encoding="utf-8") as stat_file:
            # The command name is parenthesized and may itself contain ``)``.
            return stat_file.read().rsplit(") ", 1)[1][:1]
    except FileNotFoundError:
        if os.path.isdir(proc_root):
            return "X"
    except (IndexError, OSError):
        pass

    # macOS and other POSIX hosts do not expose /proc. ``ps`` lets us
    # distinguish a zombie (which still responds to kill(pid, 0)) from a live
    # process without adding a runtime dependency.
    try:
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    state = result.stdout.strip()
    if result.returncode != 0 or not state:
        return "X"
    return state[:1]


def get_python_executable() -> str:
    """Return a Python interpreter that is known to work.

    The running interpreter wins: on Windows, ``shutil.which("python3")``
    resolves to the Microsoft Store *App Execution Alias* under
    ``WindowsApps`` for many machines, and that stub exits with code 9009
    (printing an install prompt) instead of running code. Frozen bundles have
    no interpreter to borrow, so they fall back to PATH lookup.

    The result is a *command name or absolute path* that callers can hand to
    :mod:`subprocess` directly when ``shell=False``, and must be shell-quoted
    (:func:`shlex.quote`) before being interpolated into a ``shell=True``
    command string — paths on Windows often contain spaces.
    """
    if not getattr(sys, "frozen", False) and sys.executable:
        return sys.executable
    for name in ("python3", "python"):
        candidate = shutil.which(name)
        if candidate and "windowsapps" not in candidate.lower():
            return candidate
    return shutil.which("python3") or shutil.which("python") or "python3"


def open_browser(url: str) -> None:
    """Open *url* in the user's default browser, with a Windows fast-path.

    :func:`webbrowser.open` is the cross-platform default, but on Windows it
    sometimes blocks or fails inside a console host. :func:`os.startfile`
    hands the URL to the OS shell and returns immediately. We try that first
    on Windows and fall back to :func:`webbrowser.open` if it fails.
    """
    if platform.system() == "Windows":
        try:
            # Not ``cmd /c start "" URL``: cmd.exe would read each ``&`` in
            # the query string as a command separator and truncate the URL.
            os.startfile(url)  # type: ignore[attr-defined]
            return
        except Exception:  # noqa: BLE001 - any launch failure -> fall back
            pass
    webbrowser.open(url)


def process_alive(pid: int | None) -> bool:
    """Return ``True`` if a process with *pid* is currently running.

    Cross-platform and *non-destructive*. The common POSIX idiom
    ``os.kill(pid, 0)`` must NOT be used on Windows: there ``os.kill`` maps any
    signal to ``TerminateProcess``, so a "liveness probe" would actually kill
    the process. On Windows we inspect a process handle instead.
    """
    if not pid or pid <= 0:
        return False
    if platform.system() == "Windows":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False

    # A terminated child remains in the process table as a zombie until its
    # parent reaps it. ``kill(pid, 0)`` reports that entry as present, but it can
    # no longer execute and must not trigger force-kill waits or stale-PID reuse.
    return _posix_process_state(pid) not in {"X", "Z"}


def terminate_process(pid: int | None, *, grace_seconds: float = 3.0) -> None:
    """Terminate *pid* gracefully, escalating to a forced kill (cross-platform).

    POSIX sends ``SIGTERM`` then, after *grace_seconds*, ``SIGKILL``. Windows
    has neither; it uses ``taskkill /T`` (graceful, whole tree) then
    ``taskkill /F /T`` (force). ``signal.SIGKILL`` does not exist on Windows,
    so it is only referenced inside the POSIX branch.
    """
    if not process_alive(pid):
        return
    is_windows = platform.system() == "Windows"

    if is_windows:
        subprocess.run(
            ["taskkill", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

    deadline = time.monotonic() + max(0.0, grace_seconds)
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


def strftime_unpadded(value: object, fmt: str) -> str:
    """``strftime`` with glibc's ``%-`` flag emulated on every platform.

    Windows' C runtime rejects ``%-d``/``%-I`` with ``ValueError: Invalid
    format string``, which broke calendar rendering and digests there. The
    unpadded tokens are replaced by markers, formatted, then restored.
    """
    if not hasattr(value, "strftime"):
        return str(value)
    tokens = (
        ("%-d", lambda: str(value.day)),
        ("%-m", lambda: str(value.month)),
        ("%-H", lambda: str(value.hour)),
        ("%-I", lambda: str(int(value.strftime("%I")))),
        ("%-M", lambda: str(value.minute)),
        ("%-S", lambda: str(value.second)),
    )
    markers: dict[str, str] = {}
    for index, (token, resolve) in enumerate(tokens):
        if token in fmt:
            marker = f"\x01{index}\x02"
            fmt = fmt.replace(token, marker)
            markers[marker] = resolve()
    text = value.strftime(fmt)
    for marker, resolved in markers.items():
        text = text.replace(marker, resolved)
    return text


__all__ = [
    "get_python_executable",
    "open_browser",
    "process_alive",
    "strftime_unpadded",
    "terminate_process",
]
