"""Productive desktop grants, verification, and risk-boundary regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.desktop.controller import (
    DesktopAccessMode,
    DesktopAccessStore,
    DesktopTargetGrant,
    ProductiveDesktopController,
    desktop_tool_runtimes,
)
from openjarvis.desktop.models import DesktopElement, DesktopRect, DesktopWindow
from openjarvis.desktop.win32 import WindowsDesktopError
from openjarvis.tasks.policy import RiskLevel


class ProductiveFakeBackend:
    def __init__(self, executable: Path) -> None:
        self.executable = str(executable)
        self.window = DesktopWindow(
            10, 42, "Granted Editor", DesktopRect(-300, 20, 500, 620), 144
        )
        self.screenshots = 0
        self.clicked = False
        self.desktop_name = "Default"

    def input_desktop_name(self):
        return self.desktop_name

    def semantic_status(self):
        return "windows_uia"

    def interrupt_semantic(self):
        return None

    def visible_windows(self):
        return (self.window,)

    def process_executable(self, process_id):
        assert process_id == 42
        return self.executable

    def refresh_window(self, window):
        return window

    def elements(self, window):
        return (
            DesktopElement(11, 42, "edit", "", 100, DesktopRect(-250, 80, 300, 180)),
            DesktopElement(12, 42, "button", "Send message", 101, DesktopRect(-250, 200, -50, 250)),
        )

    def find_element(self, window, *, automation_id, role):
        return next(
            item
            for item in self.elements(window)
            if item.automation_id == automation_id and item.role == role
        )

    def is_password_element(self, window, element):
        return False

    def focus(self, window):
        return True

    def is_focused(self, window):
        return True

    def set_text(self, window, element, value):
        return value

    def click(self, window, element):
        self.clicked = True

    def screenshot_window(self, window):
        self.screenshots += 1
        return b"BM" + str(self.screenshots).encode()


def _controller(tmp_path: Path):
    executable = tmp_path / "editor.exe"
    executable.write_bytes(b"not executed")
    store = DesktopAccessStore(tmp_path / "desktop-access.json")
    store.put(
        DesktopTargetGrant(
            target_id="editor",
            label="Editor",
            executable=str(executable),
            title_contains="Granted",
            mode=DesktopAccessMode.INTERACT,
            capabilities=("inspect", "screenshot", "focus", "type", "click"),
        )
    )
    backend = ProductiveFakeBackend(executable)
    return ProductiveDesktopController(
        backend=backend,
        access_store=store,
        artifact_root=tmp_path / "artifacts",
    ), backend


def test_persistent_grant_attaches_to_one_existing_matching_process(tmp_path: Path) -> None:
    controller, _backend = _controller(tmp_path)
    window = controller.connect("editor")
    assert window.process_id == 42
    assert DesktopAccessStore(tmp_path / "desktop-access.json").list()[0].target_id == "editor"
    assert controller.inspect("editor")["verified"] is True


def test_normal_click_refuses_a_sensitive_control_without_allow_once(tmp_path: Path) -> None:
    controller, backend = _controller(tmp_path)
    controller.connect("editor")
    with pytest.raises(WindowsDesktopError, match="approval-scoped"):
        controller.click("editor", 101, "button")
    assert backend.clicked is False


def test_secure_desktop_is_a_hard_boundary(tmp_path: Path) -> None:
    controller, backend = _controller(tmp_path)
    backend.desktop_name = "Winlogon"
    with pytest.raises(WindowsDesktopError, match="Secure Desktop"):
        controller.connect("editor")


def test_tool_risks_keep_normal_and_sensitive_clicks_separate(tmp_path: Path) -> None:
    controller, _backend = _controller(tmp_path)
    manifests = {manifest.tool_id: manifest for manifest, _ in desktop_tool_runtimes(controller)}
    assert manifests["desktop.click"].risk_level is RiskLevel.REVERSIBLE_WORKSPACE
    assert manifests["desktop.click"].required_approval is False
    assert manifests["desktop.sensitive_click"].risk_level is RiskLevel.DESTRUCTIVE_OR_SENSITIVE
    assert manifests["desktop.sensitive_click"].required_approval is True
    assert manifests["desktop.visual_click"].required_approval is True
