"""Productive, policy-scoped Windows desktop controller.

This is deliberately separate from ``WindowsDesktopSession``, which remains the
owned-process test harness. Productive access attaches only to user-configured
executables and still routes mutations through ToolActionService.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from openjarvis.desktop.models import DesktopArtifact, DesktopRect, DesktopWindow
from openjarvis.desktop.win32 import Win32SemanticBackend, WindowsDesktopError
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tasks.types import ExecutionLane
from openjarvis.tools.action_service import RegisteredToolRuntime
from openjarvis.tools.actions import ToolProposal, VerificationResult
from openjarvis.tools.manifest import (
    IdempotencyPolicy,
    NetworkPolicy,
    SecretPolicy,
    SideEffectClass,
    ToolManifest,
)


class DesktopAccessMode(str, Enum):
    OFF = "off"
    OBSERVE = "observe"
    INTERACT = "interact"


@dataclass(frozen=True, slots=True)
class DesktopTargetGrant:
    target_id: str
    label: str
    executable: str
    title_contains: str
    mode: DesktopAccessMode
    capabilities: tuple[str, ...]


class DesktopAccessStore:
    """Persist non-secret, user-owned application grants atomically."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self.path.exists():
            self._write({"schema_version": 1, "targets": []})

    def list(self) -> tuple[DesktopTargetGrant, ...]:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WindowsDesktopError(
                    "desktop access configuration is invalid"
                ) from exc
            targets: list[DesktopTargetGrant] = []
            for item in payload.get("targets", []):
                if not isinstance(item, dict):
                    continue
                try:
                    targets.append(
                        DesktopTargetGrant(
                            target_id=str(item["target_id"]),
                            label=str(item["label"])[:160],
                            executable=str(
                                Path(str(item["executable"])).resolve(strict=False)
                            ),
                            title_contains=str(item["title_contains"])[:256],
                            mode=DesktopAccessMode(str(item.get("mode", "off"))),
                            capabilities=tuple(
                                sorted(
                                    {
                                        str(value)
                                        for value in item.get("capabilities", [])
                                    }
                                )
                            ),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            return tuple(targets)

    def put(self, grant: DesktopTargetGrant) -> DesktopTargetGrant:
        if not grant.target_id or len(grant.target_id) > 80:
            raise ValueError("invalid desktop target ID")
        if not Path(grant.executable).is_absolute():
            raise ValueError("desktop executable must be an absolute path")
        allowed = {
            "inspect",
            "screenshot",
            "focus",
            "window",
            "launch",
            "type",
            "click",
            "hotkey",
            "scroll",
            "visual_click",
            "clipboard",
        }
        if not set(grant.capabilities).issubset(allowed):
            raise ValueError("desktop grant contains an unsupported capability")
        if grant.mode is DesktopAccessMode.OBSERVE and set(grant.capabilities) - {
            "inspect",
            "screenshot",
        }:
            raise ValueError("observe mode cannot grant interaction")
        with self._lock:
            current = {item.target_id: item for item in self.list()}
            current[grant.target_id] = grant
            self._write(
                {
                    "schema_version": 1,
                    "targets": [
                        {**asdict(item), "mode": item.mode.value}
                        for item in sorted(
                            current.values(), key=lambda value: value.target_id
                        )
                    ],
                }
            )
        return grant

    def _write(self, payload: dict[str, Any]) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


class ProductiveDesktopController:
    """Attach to explicitly granted existing windows with verification and audit."""

    def __init__(
        self,
        *,
        backend: Win32SemanticBackend,
        access_store: DesktopAccessStore,
        artifact_root: str | Path,
        event_sink=None,
        flow_authority=None,
    ) -> None:
        self.backend = backend
        self.access_store = access_store
        self.artifact_root = Path(artifact_root).resolve(strict=False)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.event_sink = event_sink or (lambda _name, _payload: None)
        self.flow_authority = flow_authority
        self._windows: dict[str, DesktopWindow] = {}
        self._lock = threading.RLock()
        self._interrupted = threading.Event()
        self._interrupt_epoch = 0
        self._last_action: dict[str, Any] | None = None
        self._audit: list[dict[str, Any]] = []

    def status(self) -> dict[str, Any]:
        grants = self.access_store.list()
        secure_boundary = "unavailable"
        if os.name == "nt":
            secure_boundary = self.backend.input_desktop_name()
        active_target = next(
            (target_id for target_id in self._windows if target_id), None
        )
        active_window = self._windows.get(active_target or "")
        target_monitor = ""
        if active_window is not None:
            center_x = active_window.bounds.left + active_window.bounds.width // 2
            center_y = active_window.bounds.top + active_window.bounds.height // 2
            try:
                target_monitor = next(
                    (
                        monitor.device
                        for monitor in self.backend.monitors()
                        if monitor.bounds.left <= center_x < monitor.bounds.right
                        and monitor.bounds.top <= center_y < monitor.bounds.bottom
                    ),
                    "",
                )
            except WindowsDesktopError:
                target_monitor = ""
        return {
            "available": os.name == "nt",
            "mode": "configured"
            if any(item.mode is not DesktopAccessMode.OFF for item in grants)
            else "off",
            "secure_desktop": secure_boundary,
            "secure_desktop_blocked": secure_boundary != "Default",
            "interrupt_requested": self._interrupted.is_set(),
            "interrupt_available": True,
            "current_target_id": active_target,
            "current_window": active_window.title[:256] if active_window else "",
            "target_monitor": target_monitor,
            "target_dpi": active_window.dpi if active_window else None,
            "target_scale": active_window.dpi / 96.0 if active_window else None,
            "semantic_backend": self.backend.semantic_status(),
            "last_action": self._last_action,
            "audit": list(self._audit[-20:]),
            "unsupported_boundaries": [
                "UAC Secure Desktop",
                "Windows sign-in screen",
                "other user sessions",
                "protected password fields",
            ],
            "targets": [
                {
                    "target_id": item.target_id,
                    "label": item.label,
                    "executable": item.executable,
                    "title_contains": item.title_contains,
                    "mode": item.mode.value,
                    "capabilities": list(item.capabilities),
                    "connected": item.target_id in self._windows,
                }
                for item in grants
            ],
        }

    def connect(self, target_id: str) -> DesktopWindow:
        grant = self._grant(target_id, "inspect")
        self._require_default_desktop()
        if target_id.startswith("window:") and target_id in self._windows:
            return self.backend.refresh_window(self._windows[target_id])
        expected_executable = str(
            Path(grant.executable).resolve(strict=False)
        ).casefold()
        matches = []
        for window in self.backend.visible_windows():
            if grant.title_contains.casefold() not in window.title.casefold():
                continue
            try:
                executable = str(
                    Path(self.backend.process_executable(window.process_id)).resolve(
                        strict=False
                    )
                ).casefold()
            except WindowsDesktopError:
                continue
            if executable == expected_executable:
                matches.append(window)
        if len(matches) != 1:
            raise WindowsDesktopError(
                f"desktop target requires exactly one matching window; found {len(matches)}"
            )
        self._windows[target_id] = matches[0]
        self._interrupted.clear()
        self._emit(
            "desktop.connected", target_id, {"process_id": matches[0].process_id}
        )
        self._record("connect", target_id, True, {"process_id": matches[0].process_id})
        return matches[0]

    def list_monitors(self) -> dict[str, Any]:
        self._require_global_access("inspect")
        self._require_default_desktop()
        monitors = self.backend.monitors()
        return {
            "verified": True,
            "monitors": [
                {
                    "device": item.device,
                    "bounds": asdict(item.bounds),
                    "work_area": asdict(item.work_area),
                    "primary": item.primary,
                }
                for item in monitors
            ],
        }

    def list_windows(self) -> dict[str, Any]:
        self._require_global_access("inspect")
        self._require_default_desktop()
        windows = []
        for item in self.backend.visible_windows()[:250]:
            try:
                executable = self.backend.process_executable(item.process_id)
            except WindowsDesktopError:
                executable = "unavailable"
            windows.append(
                {
                    "target_id": f"window:{item.handle}",
                    "title": item.title[:256],
                    "process_id": item.process_id,
                    "executable": executable,
                    "bounds": asdict(item.bounds),
                    "dpi": item.dpi,
                    "scale": item.dpi / 96.0,
                }
            )
            self._windows[f"window:{item.handle}"] = item
        return {"verified": True, "windows": windows}

    def list_browser_windows(self) -> dict[str, Any]:
        """Return existing owner browser windows without opening a new profile."""

        observed = self.list_windows()
        browser_names = {"brave", "chrome", "firefox", "msedge", "opera", "vivaldi"}
        windows = [
            item
            for item in observed["windows"]
            if Path(str(item["executable"])).stem.casefold() in browser_names
        ]
        return {"verified": True, "windows": windows}

    def browser_navigate(
        self,
        target_id: str,
        url: str,
        *,
        new_tab: bool = False,
    ) -> dict[str, Any]:
        """Navigate an existing browser window while preserving its signed-in profile."""

        parsed = urlsplit(url.strip())
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("browser URL must be an absolute HTTP(S) URL")
        if len(url) > 8192:
            raise ValueError("browser URL exceeds 8192 characters")
        window = self._window(target_id)
        self._focus(window)
        before = self.screenshot(target_id)
        previous_clipboard: str | None
        try:
            previous_clipboard = self.backend.clipboard_read()
        except WindowsDesktopError:
            previous_clipboard = None
        try:
            if new_tab:
                self.backend.send_hotkey(window, "ctrl+t")
            self.backend.send_hotkey(window, "ctrl+l")
            self.backend.clipboard_write(url)
            self.backend.send_hotkey(window, "ctrl+v")
        finally:
            if previous_clipboard is not None:
                self.backend.clipboard_write(previous_clipboard)
        self.backend.send_hotkey(window, "enter")
        time.sleep(0.35)
        after_window = self.backend.refresh_window(window)
        after = self.screenshot(target_id)
        verified = (
            after_window.process_id == window.process_id
            and self.backend.is_focused(after_window)
            and before.sha256 != after.sha256
        )
        self._record(
            "browser_navigate",
            target_id,
            verified,
            {"artifact_id": after.artifact_id, "new_tab": new_tab},
        )
        return {
            "target_id": target_id,
            "artifact_id": after.artifact_id,
            "new_tab": new_tab,
            "verified": verified,
        }

    def browser_close_tab(self, target_id: str) -> dict[str, Any]:
        """Close the active tab in an existing browser window."""

        return self.hotkey(target_id, "ctrl+w")

    def active_window(self) -> dict[str, Any]:
        self._require_global_access("inspect")
        self._require_default_desktop()
        window = self.backend.active_window()
        return {
            "verified": True,
            "title": window.title[:256],
            "process_id": window.process_id,
            "executable": self.backend.process_executable(window.process_id),
            "bounds": asdict(window.bounds),
            "dpi": window.dpi,
            "scale": window.dpi / 96.0,
        }

    def inspect(self, target_id: str) -> dict[str, Any]:
        self._grant(target_id, "inspect")
        window = self._window(target_id)
        elements = self.backend.elements(window)
        self._emit("desktop.observed", target_id, {"element_count": len(elements)})
        return {
            "target_id": target_id,
            "window_title": window.title[:256],
            "process_id": window.process_id,
            "verified": True,
            "semantic_backend": self.backend.semantic_status(),
            "elements": [
                {
                    "automation_id": element.automation_id,
                    "role": element.role,
                    "name": element.name[:256],
                    "value": "" if element.protected else element.value[:512],
                    "protected": element.protected,
                    "bounds": asdict(element.bounds),
                }
                for element in elements[:250]
            ],
        }

    def screenshot(self, target_id: str) -> DesktopArtifact:
        self._grant(target_id, "screenshot")
        window = self._window(target_id)
        data = self.backend.screenshot_window(window)
        artifact_id = f"desktop_artifact_{uuid.uuid4().hex}"
        path = self.artifact_root / f"{artifact_id}.bmp"
        path.write_bytes(data)
        artifact = DesktopArtifact(
            artifact_id=artifact_id,
            path=str(path),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            window_handle=window.handle,
        )
        self._emit("desktop.screenshot", target_id, {"artifact_id": artifact_id})
        return artifact

    def screenshot_region(
        self, target_id: str, left: int, top: int, right: int, bottom: int
    ) -> DesktopArtifact:
        self._grant(target_id, "screenshot")
        window = self.backend.refresh_window(self._window(target_id))
        bounds = DesktopRect(left, top, right, bottom)
        if (
            bounds.left < window.bounds.left
            or bounds.top < window.bounds.top
            or bounds.right > window.bounds.right
            or bounds.bottom > window.bounds.bottom
        ):
            raise WindowsDesktopError("screenshot region escaped the granted window")
        data = self.backend.screenshot_region(bounds)
        artifact_id = f"desktop_artifact_{uuid.uuid4().hex}"
        path = self.artifact_root / f"{artifact_id}.bmp"
        path.write_bytes(data)
        artifact = DesktopArtifact(
            artifact_id=artifact_id,
            path=str(path),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            window_handle=window.handle,
        )
        self._record("screenshot_region", target_id, True, {"artifact_id": artifact_id})
        return artifact

    def focus(self, target_id: str) -> dict[str, Any]:
        self._grant(target_id, "focus", require_interact=True)
        window = self._window(target_id)
        self._focus(window)
        verified = self.backend.is_focused(window)
        self._record("focus", target_id, verified)
        return {"target_id": target_id, "verified": verified}

    def set_window_state(self, target_id: str, state: str) -> dict[str, Any]:
        self._grant(target_id, "window", require_interact=True)
        window = self._window(target_id)
        observed = self.backend.set_window_state(window, state)
        verified = observed == state
        self._record("window_state", target_id, verified, {"state": observed})
        return {"target_id": target_id, "state": observed, "verified": verified}

    def move_window(
        self, target_id: str, left: int, top: int, width: int, height: int
    ) -> dict[str, Any]:
        self._grant(target_id, "window", require_interact=True)
        window = self._window(target_id)
        display = self.backend.display_context(window)
        requested = DesktopRect(left, top, left + width, top + height)
        if (
            requested.left < display.virtual_left
            or requested.top < display.virtual_top
            or requested.right > display.virtual_left + display.virtual_width
            or requested.bottom > display.virtual_top + display.virtual_height
        ):
            raise WindowsDesktopError("window move escaped the virtual desktop")
        observed = self.backend.move_window(window, requested)
        self._windows[target_id] = observed
        verified = observed.bounds == requested
        self._record(
            "move_window", target_id, verified, {"bounds": asdict(observed.bounds)}
        )
        return {
            "target_id": target_id,
            "bounds": asdict(observed.bounds),
            "dpi": observed.dpi,
            "verified": verified,
        }

    def launch(self, target_id: str) -> dict[str, Any]:
        grant = self._grant(target_id, "launch", require_interact=True)
        self._require_default_desktop()
        executable = Path(grant.executable).resolve(strict=True)
        try:
            existing = self.connect(target_id)
        except WindowsDesktopError as exc:
            if "found 0" not in str(exc):
                raise
        else:
            self._record(
                "launch_existing",
                target_id,
                True,
                {"process_id": existing.process_id},
            )
            return {
                "target_id": target_id,
                "process_id": existing.process_id,
                "window_title": existing.title[:256],
                "already_running": True,
                "verified": True,
            }
        process = subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        deadline = time.monotonic() + 12.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            self._check_interrupt()
            try:
                window = self.connect(target_id)
                verified = (
                    window.process_id == process.pid
                    or self.backend.process_executable(window.process_id).casefold()
                    == str(executable).casefold()
                )
                self._record(
                    "launch", target_id, verified, {"process_id": window.process_id}
                )
                return {
                    "target_id": target_id,
                    "process_id": window.process_id,
                    "window_title": window.title[:256],
                    "verified": verified,
                }
            except WindowsDesktopError as exc:
                last_error = exc
                time.sleep(0.15)
        raise WindowsDesktopError(
            "launched application did not expose the granted window"
        ) from last_error

    def launch_application(
        self, executable: str, arguments: list[str] | None = None
    ) -> dict[str, Any]:
        if not (self.flow_authority and self.flow_authority.is_flow()):
            raise WindowsDesktopError("application launch requires Flow mode")
        self._require_default_desktop()
        path = Path(executable).expanduser().resolve(strict=True)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        process = subprocess.Popen(
            [str(path), *(arguments or [])],
            cwd=str(path.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            self._check_interrupt()
            for window in self.backend.visible_windows():
                if window.process_id == process.pid:
                    target_id = f"window:{window.handle}"
                    self._windows[target_id] = window
                    return {
                        "target_id": target_id,
                        "process_id": process.pid,
                        "window_title": window.title[:256],
                        "verified": True,
                    }
            time.sleep(0.15)
        return {
            "target_id": None,
            "process_id": process.pid,
            "window_title": "",
            "verified": process.poll() is None,
        }

    def close_window(self, target_id: str) -> dict[str, Any]:
        self._grant(target_id, "window", require_interact=True)
        window = self._window(target_id)
        self.backend.close(window)
        self._windows.pop(target_id, None)
        return {"target_id": target_id, "verified": True}

    def set_text(
        self, target_id: str, automation_id: int, role: str, value: str
    ) -> dict[str, Any]:
        self._grant(target_id, "type", require_interact=True)
        if len(value) > 4000:
            raise ValueError("desktop text exceeds 4000 characters")
        with self._lock:
            window = self._window(target_id)
            self._focus(window)
            element = self.backend.find_element(
                window, automation_id=automation_id, role=role
            )
            if self.backend.is_password_element(window, element):
                raise WindowsDesktopError("protected password fields are not permitted")
            observed = self.backend.set_text(window, element, value)
            verified = observed == value
            self._emit(
                "desktop.action_verified",
                target_id,
                {
                    "kind": "semantic_text",
                    "automation_id": automation_id,
                    "verified": verified,
                },
            )
            self._record(
                "semantic_text",
                target_id,
                verified,
                {"automation_id": automation_id, "observed_length": len(observed)},
            )
            return {
                "target_id": target_id,
                "kind": "semantic_text",
                "automation_id": automation_id,
                "verified": verified,
                "observed_length": len(observed),
            }

    def click(
        self,
        target_id: str,
        automation_id: int,
        role: str,
        *,
        sensitive: bool = False,
    ) -> dict[str, Any]:
        self._grant(target_id, "click", require_interact=True)
        with self._lock:
            window = self._window(target_id)
            self._focus(window)
            before = self.screenshot(target_id)
            element = self.backend.find_element(
                window, automation_id=automation_id, role=role
            )
            sensitive_markers = {
                "buy",
                "delete",
                "install",
                "pay",
                "publish",
                "purchase",
                "send",
                "submit",
                "upload",
                "zahlen",
                "löschen",
                "senden",
                "veröffentlichen",
            }
            element_name = element.name.casefold()
            if (
                not (self.flow_authority and self.flow_authority.is_flow())
                and not sensitive
                and any(marker in element_name for marker in sensitive_markers)
            ):
                raise WindowsDesktopError(
                    "sensitive control requires the approval-scoped desktop tool"
                )
            self.backend.click(window, element)
            after = self.screenshot(target_id)
            verified = before.sha256 != after.sha256
            self._emit(
                "desktop.action_verified",
                target_id,
                {
                    "kind": "semantic_click",
                    "automation_id": automation_id,
                    "verified": verified,
                    "artifact_id": after.artifact_id,
                },
            )
            self._record(
                "sensitive_click" if sensitive else "semantic_click",
                target_id,
                verified,
                {"automation_id": automation_id, "artifact_id": after.artifact_id},
            )
            return {
                "target_id": target_id,
                "kind": "semantic_click",
                "automation_id": automation_id,
                "verified": verified,
                "artifact_id": after.artifact_id,
            }

    def clipboard_read(self, target_id: str) -> dict[str, Any]:
        self._grant(target_id, "clipboard", require_interact=True)
        self._window(target_id)
        value = self.backend.clipboard_read()
        if len(value) > 16_384:
            value = value[:16_384]
        self._record("clipboard_read", target_id, True, {"length": len(value)})
        return {"target_id": target_id, "value": value, "verified": True}

    def clipboard_write(self, target_id: str, value: str) -> dict[str, Any]:
        self._grant(target_id, "clipboard", require_interact=True)
        self._window(target_id)
        if len(value) > 16_384:
            raise ValueError("clipboard text exceeds 16384 characters")
        observed = self.backend.clipboard_write(value)
        verified = observed == value
        self._record("clipboard_write", target_id, verified, {"length": len(value)})
        return {"target_id": target_id, "length": len(observed), "verified": verified}

    def hotkey(self, target_id: str, chord: str) -> dict[str, Any]:
        self._grant(target_id, "hotkey", require_interact=True)
        allowed = {
            "ctrl+a",
            "ctrl+c",
            "ctrl+f",
            "ctrl+l",
            "ctrl+n",
            "ctrl+o",
            "ctrl+p",
            "ctrl+r",
            "ctrl+s",
            "ctrl+t",
            "ctrl+v",
            "ctrl+w",
            "ctrl+x",
            "ctrl+y",
            "ctrl+z",
            "alt+f4",
            "alt+left",
            "alt+right",
            "enter",
            "esc",
            "shift+tab",
            "tab",
        }
        if (
            not (self.flow_authority and self.flow_authority.is_flow())
            and chord.casefold() not in allowed
        ):
            raise WindowsDesktopError("hotkey is not allowlisted")
        if not re.fullmatch(r"[a-z0-9+_-]{1,40}", chord.casefold()):
            raise WindowsDesktopError("hotkey syntax is invalid")
        window = self._window(target_id)
        self._focus(window)
        before = self.backend.refresh_window(window)
        self.backend.send_hotkey(window, chord)
        after = self.backend.refresh_window(window)
        verified = before.process_id == after.process_id and self.backend.is_focused(
            after
        )
        self._record("hotkey", target_id, verified, {"chord": chord.casefold()})
        return {"target_id": target_id, "chord": chord.casefold(), "verified": verified}

    def scroll(self, target_id: str, delta: int) -> dict[str, Any]:
        self._grant(target_id, "scroll", require_interact=True)
        if delta == 0 or abs(delta) > 1200:
            raise ValueError("scroll delta must be between -1200 and 1200")
        window = self._window(target_id)
        self._focus(window)
        before = self.screenshot(target_id)
        self.backend.scroll(window, delta)
        time.sleep(0.08)
        after = self.screenshot(target_id)
        verified = before.sha256 != after.sha256
        self._record("scroll", target_id, verified, {"artifact_id": after.artifact_id})
        return {
            "target_id": target_id,
            "artifact_id": after.artifact_id,
            "verified": verified,
        }

    def visual_click(self, target_id: str, x: int, y: int) -> dict[str, Any]:
        self._grant(target_id, "visual_click", require_interact=True)
        window = self.backend.refresh_window(self._window(target_id))
        self._windows[target_id] = window
        self._focus(window)
        display = self.backend.display_context(window)
        before = self.screenshot(target_id)
        if (
            not window.bounds.left <= x < window.bounds.right
            or not window.bounds.top <= y < window.bounds.bottom
        ):
            raise WindowsDesktopError("visual click escaped the current window bounds")
        self._check_interrupt()
        self.backend.coordinate_click(window, x, y)
        time.sleep(0.08)
        after_window = self.backend.refresh_window(window)
        after = self.screenshot(target_id)
        verified = (
            before.sha256 != after.sha256
            and after_window.process_id == window.process_id
            and display.dpi == after_window.dpi
        )
        self._record(
            "visual_click",
            target_id,
            verified,
            {"artifact_id": after.artifact_id, "dpi": display.dpi},
        )
        return {
            "target_id": target_id,
            "artifact_id": after.artifact_id,
            "verified": verified,
        }

    def interrupt(self) -> None:
        self._interrupted.set()
        self._interrupt_epoch += 1
        epoch = self._interrupt_epoch
        self.backend.interrupt_semantic()
        self._record("interrupt", "global", True)
        self.event_sink("desktop.interrupted", {})
        reset = threading.Timer(1.0, self._clear_completed_interrupt, args=(epoch,))
        reset.daemon = True
        reset.start()

    def close(self) -> None:
        self.interrupt()
        self._windows.clear()

    def _window(self, target_id: str) -> DesktopWindow:
        self._check_interrupt()
        self._require_default_desktop()
        window = self._windows.get(target_id)
        if window is None:
            window = self.connect(target_id)
        expected = str(
            Path(self._grant(target_id, "inspect").executable).resolve(strict=False)
        )
        observed = str(
            Path(self.backend.process_executable(window.process_id)).resolve(
                strict=False
            )
        )
        if expected.casefold() != observed.casefold():
            self._windows.pop(target_id, None)
            raise WindowsDesktopError("desktop process identity changed")
        return window

    def _grant(
        self, target_id: str, capability: str, *, require_interact: bool = False
    ) -> DesktopTargetGrant:
        grant = next(
            (item for item in self.access_store.list() if item.target_id == target_id),
            None,
        )
        if self.flow_authority and self.flow_authority.is_flow():
            if grant is not None:
                return DesktopTargetGrant(
                    target_id=grant.target_id,
                    label=grant.label,
                    executable=grant.executable,
                    title_contains=grant.title_contains,
                    mode=DesktopAccessMode.INTERACT,
                    capabilities=(
                        "inspect",
                        "screenshot",
                        "focus",
                        "window",
                        "launch",
                        "type",
                        "click",
                        "hotkey",
                        "scroll",
                        "visual_click",
                        "clipboard",
                    ),
                )
            if target_id.startswith("window:"):
                try:
                    handle = int(target_id.split(":", 1)[1])
                    window = next(
                        item
                        for item in self.backend.visible_windows()
                        if item.handle == handle
                    )
                except (ValueError, StopIteration) as exc:
                    raise WindowsDesktopError("desktop window is unavailable") from exc
                self._windows[target_id] = window
                return DesktopTargetGrant(
                    target_id=target_id,
                    label=window.title[:160],
                    executable=self.backend.process_executable(window.process_id),
                    title_contains=window.title[:256],
                    mode=DesktopAccessMode.INTERACT,
                    capabilities=(
                        "inspect",
                        "screenshot",
                        "focus",
                        "window",
                        "launch",
                        "type",
                        "click",
                        "hotkey",
                        "scroll",
                        "visual_click",
                        "clipboard",
                    ),
                )
        if grant is None or grant.mode is DesktopAccessMode.OFF:
            raise WindowsDesktopError("desktop target is not enabled")
        if require_interact and grant.mode is not DesktopAccessMode.INTERACT:
            raise WindowsDesktopError("desktop target is observe-only")
        if capability not in grant.capabilities:
            raise WindowsDesktopError(
                f"desktop capability is not granted: {capability}"
            )
        return grant

    def _require_global_access(self, capability: str) -> None:
        if self.flow_authority and self.flow_authority.is_flow():
            return
        if not any(
            item.mode is not DesktopAccessMode.OFF and capability in item.capabilities
            for item in self.access_store.list()
        ):
            raise WindowsDesktopError(
                f"desktop capability is not persistently granted: {capability}"
            )

    def _focus(self, window: DesktopWindow) -> None:
        self._check_interrupt()
        if not self.backend.focus(window) or not self.backend.is_focused(window):
            raise WindowsDesktopError("desktop focus could not be verified")

    def _check_interrupt(self) -> None:
        if self._interrupted.is_set():
            raise WindowsDesktopError("desktop controller interrupted")

    def _clear_completed_interrupt(self, epoch: int) -> None:
        if self._interrupt_epoch == epoch:
            self._interrupted.clear()

    def _require_default_desktop(self) -> None:
        name = self.backend.input_desktop_name()
        if name != "Default":
            raise WindowsDesktopError(
                "Secure Desktop/UAC/lock-screen interaction is not permitted"
            )

    def _emit(self, event: str, target_id: str, payload: dict[str, Any]) -> None:
        self.event_sink(event, {"target_id": target_id, **payload})

    def _record(
        self,
        action: str,
        target_id: str,
        verified: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        value = {
            "action": action,
            "target_id": target_id,
            "verified": verified,
            "timestamp": time.time(),
            "details": details or {},
        }
        self._last_action = value
        self._audit.append(value)
        del self._audit[:-100]


def desktop_tool_runtimes(
    controller: ProductiveDesktopController,
) -> tuple[tuple[ToolManifest, RegisteredToolRuntime], ...]:
    """Return trusted desktop manifests and verified runtimes for startup registration."""

    common = {
        "version": "1.0.0",
        "supported_platforms": ("windows",),
        "allowed_lanes": (ExecutionLane.INTERACTIVE,),
        "timeout": 20.0,
        "max_retries": 0,
        "allowed_roots": (),
        "network_policy": NetworkPolicy.DENY,
        "secret_policy": SecretPolicy.REJECT,
        "log_redaction_policy": "credentials_and_sensitive_values",
    }

    def verify(_proposal: ToolProposal, output: Any) -> VerificationResult:
        passed = isinstance(output, dict) and output.get("verified") is True
        return VerificationResult(
            passed=passed,
            observed_state="verified" if passed else "postcondition_not_observed",
            expected_state="verified desktop postcondition",
            artifact_ids=(str(output["artifact_id"]),)
            if passed and output.get("artifact_id")
            else (),
        )

    inspect_manifest = ToolManifest(
        tool_id="desktop.inspect",
        name="desktop.inspect",
        description="Inspect semantic controls in one explicitly granted existing Windows application.",
        input_schema={
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "minLength": 1, "maxLength": 80}
            },
            "required": ["target_id"],
        },
        output_schema={"type": "object"},
        capability="desktop:observe",
        risk_level=RiskLevel.READ_ONLY,
        idempotency_policy=IdempotencyPolicy.SAFE_RETRY,
        side_effect_class=SideEffectClass.LOCAL_READ,
        verification_strategy="verify_process_window_and_semantic_tree",
        undo_strategy="not_applicable",
        required_approval=False,
        **common,
    )
    type_manifest = ToolManifest(
        tool_id="desktop.type",
        name="desktop.type",
        description="Type into a semantic edit control of an explicitly granted Windows application.",
        input_schema={
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "automation_id": {"type": "integer"},
                "role": {"type": "string", "enum": ["edit", "document"]},
                "value": {"type": "string", "maxLength": 4000},
            },
            "required": ["target_id", "automation_id", "role", "value"],
        },
        output_schema={"type": "object"},
        capability="desktop:interact",
        risk_level=RiskLevel.REVERSIBLE_WORKSPACE,
        idempotency_policy=IdempotencyPolicy.KEY_REQUIRED,
        side_effect_class=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
        verification_strategy="read_back_exact_control_text",
        undo_strategy="manual_or_tool_specific",
        required_approval=False,
        **common,
    )
    click_manifest = ToolManifest(
        tool_id="desktop.click",
        name="desktop.click",
        description="Click a semantic button in an explicitly granted existing Windows application.",
        input_schema={
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "automation_id": {"type": "integer"},
                "role": {
                    "type": "string",
                    "enum": [
                        "button",
                        "checkbox",
                        "hyperlink",
                        "listitem",
                        "menuitem",
                        "radiobutton",
                        "tabitem",
                        "treeitem",
                    ],
                },
            },
            "required": ["target_id", "automation_id", "role"],
        },
        output_schema={"type": "object"},
        capability="desktop:interact",
        risk_level=RiskLevel.REVERSIBLE_WORKSPACE,
        idempotency_policy=IdempotencyPolicy.NEVER_AFTER_UNKNOWN_EFFECT,
        side_effect_class=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
        verification_strategy="compare_bounded_before_after_window_artifacts",
        undo_strategy="manual_or_tool_specific",
        required_approval=False,
        **common,
    )

    def make_manifest(
        tool_id: str,
        description: str,
        input_schema: dict[str, Any],
        *,
        capability: str,
        risk: RiskLevel,
        side_effect: SideEffectClass,
    ) -> ToolManifest:
        return ToolManifest(
            tool_id=tool_id,
            name=tool_id,
            description=description,
            input_schema=input_schema,
            output_schema={"type": "object"},
            capability=capability,
            risk_level=risk,
            idempotency_policy=(
                IdempotencyPolicy.SAFE_RETRY
                if risk is RiskLevel.READ_ONLY
                else IdempotencyPolicy.NEVER_AFTER_UNKNOWN_EFFECT
            ),
            side_effect_class=side_effect,
            verification_strategy="observe_bounded_desktop_postcondition",
            undo_strategy=(
                "not_applicable"
                if risk is RiskLevel.READ_ONLY
                else "manual_or_tool_specific"
            ),
            required_approval=False,
            **common,
        )

    target_schema = {
        "type": "object",
        "properties": {
            "target_id": {"type": "string", "minLength": 1, "maxLength": 80}
        },
        "required": ["target_id"],
    }
    empty_schema = {"type": "object", "properties": {}, "required": []}
    read_only = {
        "desktop.monitors": (
            "List all Windows monitors with virtual coordinates and work areas.",
            empty_schema,
            controller.list_monitors,
        ),
        "desktop.windows": (
            "List visible windows with process identity, bounds, DPI and scale.",
            empty_schema,
            controller.list_windows,
        ),
        "desktop.active_window": (
            "Observe the currently focused Windows application.",
            empty_schema,
            controller.active_window,
        ),
    }

    def artifact_payload(artifact: DesktopArtifact) -> dict[str, Any]:
        return {
            "verified": True,
            "artifact_id": artifact.artifact_id,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
        }

    extra: list[tuple[ToolManifest, RegisteredToolRuntime]] = []
    for tool_id, (description, schema, handler) in read_only.items():
        extra.append(
            (
                make_manifest(
                    tool_id,
                    description,
                    schema,
                    capability="desktop:observe",
                    risk=RiskLevel.READ_ONLY,
                    side_effect=SideEffectClass.LOCAL_READ,
                ),
                RegisteredToolRuntime(
                    handler=lambda _args, call=handler: call(), verifier=verify
                ),
            )
        )

    extra.extend(
        [
            (
                make_manifest(
                    "desktop.launch_application",
                    "Launch any installed application in Flow mode and return its window target.",
                    {
                        "type": "object",
                        "properties": {
                            "executable": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 4096,
                            },
                            "arguments": {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 4096},
                                "maxItems": 128,
                            },
                        },
                        "required": ["executable"],
                    },
                    capability="desktop:launch",
                    risk=RiskLevel.EXTERNAL_PREPARATION,
                    side_effect=SideEffectClass.VISIBLE_PREPARATION,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.launch_application(
                        str(args["executable"]),
                        [str(value) for value in args.get("arguments", [])],
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.close_window",
                    "Close a visible application window in Flow mode.",
                    target_schema,
                    capability="desktop:interact",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.close_window(
                        str(args["target_id"])
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.screenshot",
                    "Capture the currently verified granted application window as a short-lived artifact.",
                    target_schema,
                    capability="desktop:observe",
                    risk=RiskLevel.READ_ONLY,
                    side_effect=SideEffectClass.LOCAL_READ,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: artifact_payload(
                        controller.screenshot(str(args["target_id"]))
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.focus",
                    "Focus one explicitly granted Windows application and verify foreground ownership.",
                    target_schema,
                    capability="desktop:interact",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.focus(str(args["target_id"])),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.window_state",
                    "Minimize, maximize or restore an explicitly granted application window.",
                    {
                        "type": "object",
                        "properties": {
                            "target_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 80,
                            },
                            "state": {
                                "type": "string",
                                "enum": ["minimized", "maximized", "restored"],
                            },
                        },
                        "required": ["target_id", "state"],
                    },
                    capability="desktop:interact",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.set_window_state(
                        str(args["target_id"]), str(args["state"])
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.move_window",
                    "Move and resize a granted window within the current multi-monitor virtual desktop.",
                    {
                        "type": "object",
                        "properties": {
                            "target_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 80,
                            },
                            "left": {"type": "integer"},
                            "top": {"type": "integer"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                        "required": ["target_id", "left", "top", "width", "height"],
                    },
                    capability="desktop:interact",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.move_window(
                        str(args["target_id"]),
                        int(args["left"]),
                        int(args["top"]),
                        int(args["width"]),
                        int(args["height"]),
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.start",
                    "Start the exact executable stored in a persistent desktop target grant and verify its window.",
                    target_schema,
                    capability="desktop:launch",
                    risk=RiskLevel.EXTERNAL_PREPARATION,
                    side_effect=SideEffectClass.VISIBLE_PREPARATION,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.launch(str(args["target_id"])),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.clipboard_read",
                    "Read bounded text from the local clipboard when clipboard access is granted.",
                    target_schema,
                    capability="desktop:interact",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.LOCAL_READ,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.clipboard_read(
                        str(args["target_id"])
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.clipboard_write",
                    "Write bounded text to the local clipboard and verify exact readback.",
                    {
                        "type": "object",
                        "properties": {
                            "target_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 80,
                            },
                            "value": {"type": "string", "maxLength": 16384},
                        },
                        "required": ["target_id", "value"],
                    },
                    capability="desktop:interact",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.clipboard_write(
                        str(args["target_id"]), str(args["value"])
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.hotkey",
                    "Send one allowlisted navigation/editing hotkey to a verified focused window.",
                    {
                        "type": "object",
                        "properties": {
                            "target_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 80,
                            },
                            "chord": {
                                "type": "string",
                                "enum": [
                                    "ctrl+a",
                                    "ctrl+c",
                                    "ctrl+f",
                                    "ctrl+v",
                                    "ctrl+x",
                                    "ctrl+y",
                                    "ctrl+z",
                                    "shift+tab",
                                    "tab",
                                ],
                            },
                        },
                        "required": ["target_id", "chord"],
                    },
                    capability="desktop:interact",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.hotkey(
                        str(args["target_id"]), str(args["chord"])
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.scroll",
                    "Scroll inside a verified focused window and compare before/after artifacts.",
                    {
                        "type": "object",
                        "properties": {
                            "target_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 80,
                            },
                            "delta": {"type": "integer"},
                        },
                        "required": ["target_id", "delta"],
                    },
                    capability="desktop:interact",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.scroll(
                        str(args["target_id"]), int(args["delta"])
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.sensitive_click",
                    (
                        "Click a semantic control whose label implies sending, "
                        "publishing, deleting, uploading or purchasing."
                    ),
                    click_manifest.input_schema,
                    capability="desktop:sensitive",
                    risk=RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
                    side_effect=SideEffectClass.EXTERNAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.click(
                        str(args["target_id"]),
                        int(args["automation_id"]),
                        str(args["role"]),
                        sensitive=True,
                    ),
                    verifier=verify,
                ),
            ),
            (
                make_manifest(
                    "desktop.visual_click",
                    "Last-resort coordinate click bounded to a freshly observed, focused, DPI-verified granted window.",
                    {
                        "type": "object",
                        "properties": {
                            "target_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 80,
                            },
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                        },
                        "required": ["target_id", "x", "y"],
                    },
                    capability="desktop:sensitive",
                    risk=RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
                    side_effect=SideEffectClass.EXTERNAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.visual_click(
                        str(args["target_id"]), int(args["x"]), int(args["y"])
                    ),
                    verifier=verify,
                ),
            ),
        ]
    )
    browser_target_schema = {
        "type": "object",
        "properties": {
            "target_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "url": {"type": "string", "minLength": 1, "maxLength": 8192},
        },
        "required": ["target_id", "url"],
    }
    extra.extend(
        [
            (
                make_manifest(
                    "browser.windows",
                    "List the owner's existing signed-in browser windows in Flow mode.",
                    empty_schema,
                    capability="browser:full",
                    risk=RiskLevel.READ_ONLY,
                    side_effect=SideEffectClass.LOCAL_READ,
                ),
                RegisteredToolRuntime(
                    handler=lambda _args: controller.list_browser_windows(),
                    verifier=verify,
                    interrupt=controller.interrupt,
                ),
            ),
            (
                make_manifest(
                    "browser.navigate",
                    "Navigate the active tab of an existing signed-in browser window.",
                    browser_target_schema,
                    capability="browser:full",
                    risk=RiskLevel.EXTERNAL_PREPARATION,
                    side_effect=SideEffectClass.VISIBLE_PREPARATION,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.browser_navigate(
                        str(args["target_id"]), str(args["url"])
                    ),
                    verifier=verify,
                    interrupt=controller.interrupt,
                ),
            ),
            (
                make_manifest(
                    "browser.open_tab",
                    "Open a URL in a new tab of an existing signed-in browser window.",
                    browser_target_schema,
                    capability="browser:full",
                    risk=RiskLevel.EXTERNAL_PREPARATION,
                    side_effect=SideEffectClass.VISIBLE_PREPARATION,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.browser_navigate(
                        str(args["target_id"]), str(args["url"]), new_tab=True
                    ),
                    verifier=verify,
                    interrupt=controller.interrupt,
                ),
            ),
            (
                make_manifest(
                    "browser.close_tab",
                    "Close the active tab in an existing signed-in browser window.",
                    target_schema,
                    capability="browser:full",
                    risk=RiskLevel.REVERSIBLE_WORKSPACE,
                    side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
                ),
                RegisteredToolRuntime(
                    handler=lambda args: controller.browser_close_tab(
                        str(args["target_id"])
                    ),
                    verifier=verify,
                    interrupt=controller.interrupt,
                ),
            ),
        ]
    )
    return (
        (
            inspect_manifest,
            RegisteredToolRuntime(
                handler=lambda args: controller.inspect(str(args["target_id"])),
                verifier=verify,
            ),
        ),
        (
            type_manifest,
            RegisteredToolRuntime(
                handler=lambda args: controller.set_text(
                    str(args["target_id"]),
                    int(args["automation_id"]),
                    str(args["role"]),
                    str(args["value"]),
                ),
                verifier=verify,
            ),
        ),
        (
            click_manifest,
            RegisteredToolRuntime(
                handler=lambda args: controller.click(
                    str(args["target_id"]),
                    int(args["automation_id"]),
                    str(args["role"]),
                ),
                verifier=verify,
            ),
        ),
        *extra,
    )


__all__ = [
    "DesktopAccessMode",
    "DesktopAccessStore",
    "DesktopTargetGrant",
    "ProductiveDesktopController",
    "desktop_tool_runtimes",
]
