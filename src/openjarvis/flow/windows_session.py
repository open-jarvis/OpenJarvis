"""Native Windows session boundary for owner-authenticated Flow sessions."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable


class WindowsSessionLockMonitor:
    """Lock Flow when Windows leaves the owner's interactive desktop."""

    def __init__(
        self,
        lock: Callable[[str], object],
        *,
        is_flow: Callable[[], bool],
        poll_seconds: float = 0.25,
        desktop_name: Callable[[], str] | None = None,
    ) -> None:
        self._lock_flow = lock
        self._is_flow = is_flow
        self._poll_seconds = poll_seconds
        self._desktop_name = desktop_name
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if os.name != "nt" or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="openjarvis-windows-session-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            self.check_once()

    def check_once(self) -> None:
        """Evaluate the native session boundary once (also used by tests)."""

        if not self._is_flow():
            return
        try:
            if self._desktop_name is None:
                from openjarvis.desktop.win32 import Win32SemanticBackend

                desktop = Win32SemanticBackend.input_desktop_name()
            else:
                desktop = self._desktop_name()
        except Exception:
            desktop = "secure-or-unavailable"
        if desktop.casefold() != "default":
            self._lock_flow("windows_session_locked")


__all__ = ["WindowsSessionLockMonitor"]
