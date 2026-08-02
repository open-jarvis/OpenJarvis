"""Owned-process Windows desktop session with semantic-first actions."""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from openjarvis.desktop.models import (
    CoordinateActionContext,
    DesktopArtifact,
    DesktopElement,
    DesktopWindow,
)
from openjarvis.desktop.win32 import Win32SemanticBackend, WindowsDesktopError


class WindowsDesktopSession:
    """Allow actions only in one process created by this session."""

    def __init__(
        self,
        *,
        backend: Win32SemanticBackend,
        artifact_root: str | Path,
        event_sink: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.backend = backend
        self.artifact_root = Path(artifact_root).resolve(strict=False)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.event_sink = event_sink or (lambda _name, _payload: None)
        self.process: subprocess.Popen[bytes] | None = None
        self.window: DesktopWindow | None = None
        self._exclusive = threading.Lock()
        self._interrupted = threading.Event()

    def start_test_application(
        self,
        *,
        executable: str | Path,
        script: str | Path,
        expected_title: str,
        allowed_root: str | Path,
        arguments: Sequence[str] = (),
        timeout: float = 10.0,
    ) -> DesktopWindow:
        if os.name != "nt":
            raise WindowsDesktopError("Windows desktop session requires Windows")
        root = Path(allowed_root).resolve(strict=True)
        script_path = Path(script).resolve(strict=True)
        try:
            script_path.relative_to(root)
        except ValueError as exc:
            raise WindowsDesktopError("test application escaped allowed root") from exc
        if self.process is not None and self.process.poll() is None:
            raise WindowsDesktopError("a desktop test application is already active")
        self.process = subprocess.Popen(
            [
                str(Path(executable).resolve(strict=True)),
                str(script_path),
                *(str(argument) for argument in arguments),
            ],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        deadline = time.monotonic() + timeout
        last_error = "window not ready"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise WindowsDesktopError(
                    f"test application exited with code {self.process.returncode}"
                )
            try:
                self.window = self.backend.find_window(self.process.pid, expected_title)
                return self.window
            except WindowsDesktopError as exc:
                last_error = str(exc)
                time.sleep(0.05)
        raise WindowsDesktopError(last_error)

    def element(self, *, automation_id: int, role: str) -> DesktopElement:
        return self.backend.find_element(
            self._require_window(), automation_id=automation_id, role=role
        )

    def set_text(self, element: DesktopElement, value: str) -> str:
        with self._exclusive:
            self._check_interrupt()
            window = self._require_window()
            self._acquire_focus(window)
            observed = self.backend.set_text(window, element, value)
            self.event_sink(
                "desktop.action_performed",
                {"kind": "semantic_text", "automation_id": element.automation_id},
            )
            self.event_sink(
                "desktop.action_verified",
                {"kind": "semantic_text", "value_matches": observed == value},
            )
            return observed

    def click(
        self,
        element: DesktopElement,
        *,
        verifier: Callable[[], bool],
    ) -> None:
        with self._exclusive:
            self._check_interrupt()
            window = self._require_window()
            self._acquire_focus(window)
            self.backend.click(window, element)
            self.event_sink(
                "desktop.action_performed",
                {"kind": "semantic_click", "automation_id": element.automation_id},
            )
            if not verifier():
                raise WindowsDesktopError("semantic click verification failed")
            self.event_sink(
                "desktop.action_verified",
                {"kind": "semantic_click", "verified": True},
            )

    def screenshot(self) -> DesktopArtifact:
        window = self._require_window()
        data = self.backend.screenshot_window(window)
        artifact_id = f"desktop_artifact_{uuid.uuid4().hex}"
        path = self.artifact_root / f"{artifact_id}.bmp"
        path.write_bytes(data)
        return DesktopArtifact(
            artifact_id=artifact_id,
            path=str(path),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            window_handle=window.handle,
        )

    def coordinate_fallback(
        self,
        context: CoordinateActionContext,
        *,
        verifier: Callable[[], bool],
    ) -> DesktopArtifact:
        with self._exclusive:
            self._check_interrupt()
            window = self._require_window()
            if context.window != window:
                raise WindowsDesktopError("coordinate context window changed")
            if not context.focused or not self.backend.is_focused(window):
                raise WindowsDesktopError("coordinate fallback requires verified focus")
            if not context.interrupt_enabled:
                raise WindowsDesktopError("coordinate fallback requires an interrupt")
            if context.display != self.backend.display_context(window):
                raise WindowsDesktopError("display/DPI context changed")
            if context.before_artifact.window_handle != window.handle:
                raise WindowsDesktopError("before screenshot does not match window")
            x = (context.target.left + context.target.right) // 2
            y = (context.target.top + context.target.bottom) // 2
            self.backend.coordinate_click(window, x, y)
            self.event_sink("desktop.action_performed", {"kind": "coordinate_fallback"})
            after = self.screenshot()
            if not verifier():
                raise WindowsDesktopError("coordinate action verification failed")
            self.event_sink(
                "desktop.action_verified",
                {"kind": "coordinate_fallback", "artifact_id": after.artifact_id},
            )
            return after

    def interrupt(self) -> None:
        self._interrupted.set()

    def close(self) -> None:
        if self.window is not None:
            try:
                self.backend.close(self.window)
            except WindowsDesktopError:
                pass
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
        self.window = None
        self.process = None

    def _require_window(self) -> DesktopWindow:
        if self.window is None or self.process is None:
            raise WindowsDesktopError("desktop session is not active")
        if self.process.poll() is not None:
            raise WindowsDesktopError("owned desktop process exited")
        if not self.backend.is_owned_process(self.window.process_id, self.process.pid):
            raise WindowsDesktopError("desktop process ownership changed")
        return self.window

    def _acquire_focus(self, window: DesktopWindow) -> None:
        if not self.backend.focus(window):
            raise WindowsDesktopError("unable to acquire owned window focus")
        self.event_sink(
            "desktop.focus_acquired",
            {"process_id": window.process_id, "window_handle": window.handle},
        )

    def _check_interrupt(self) -> None:
        if self._interrupted.is_set():
            raise WindowsDesktopError("desktop session interrupted")


__all__ = ["WindowsDesktopSession"]
