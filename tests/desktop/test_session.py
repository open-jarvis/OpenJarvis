"""Semantic desktop automation and coordinate fallback invariants."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from openjarvis.desktop import (
    CoordinateActionContext,
    DesktopArtifact,
    DesktopElement,
    DesktopRect,
    DesktopWindow,
    DisplayContext,
    Win32SemanticBackend,
    WindowsDesktopError,
    WindowsDesktopSession,
)


class FakeBackend:
    def __init__(self):
        self.focused = True
        self.text = ""
        self.clicked = False
        self.coordinate_clicked = False
        self.display = DisplayContext(1, 0, 0, 1920, 1080, 96, 1.0)

    def find_element(self, window, *, automation_id, role):
        return DesktopElement(
            automation_id,
            window.process_id,
            role,
            "synthetic",
            automation_id,
            DesktopRect(10, 10, 100, 40),
        )

    def is_owned_process(self, process_id, root_process_id):
        return process_id == root_process_id

    def focus(self, window):
        return self.focused

    def is_focused(self, window):
        return self.focused

    def set_text(self, window, element, value):
        self.text = value
        return value

    def click(self, window, element):
        self.clicked = True

    def screenshot_window(self, window):
        return b"BMsynthetic-window-only"

    def display_context(self, window):
        return self.display

    def coordinate_click(self, window, x, y):
        self.coordinate_clicked = True

    def close(self, window):
        pass


class RunningProcess:
    pid = 123

    def poll(self):
        return None


def _fake_session(tmp_path: Path):
    backend = FakeBackend()
    session = WindowsDesktopSession(backend=backend, artifact_root=tmp_path)
    session.process = RunningProcess()
    session.window = DesktopWindow(1, 123, "Synthetic", DesktopRect(0, 0, 400, 300), 96)
    return session, backend


def test_semantic_text_and_click_are_verified(tmp_path: Path) -> None:
    session, backend = _fake_session(tmp_path)
    edit = session.element(automation_id=1001, role="edit")
    button = session.element(automation_id=1002, role="button")
    assert session.set_text(edit, "Fake User") == "Fake User"
    session.click(button, verifier=lambda: backend.clicked)
    assert backend.text == "Fake User"
    assert backend.clicked is True


def test_coordinate_fallback_requires_all_context_and_verification(
    tmp_path: Path,
) -> None:
    session, backend = _fake_session(tmp_path)
    before = session.screenshot()
    context = CoordinateActionContext(
        display=backend.display,
        window=session.window,
        target=DesktopRect(10, 10, 20, 20),
        focused=True,
        before_artifact=before,
        interrupt_enabled=True,
    )
    after = session.coordinate_fallback(
        context, verifier=lambda: backend.coordinate_clicked
    )
    assert Path(after.path).exists()
    assert backend.coordinate_clicked is True


def test_coordinate_fallback_rejects_focus_loss_or_missing_interrupt(
    tmp_path: Path,
) -> None:
    session, backend = _fake_session(tmp_path)
    before = DesktopArtifact("a", "before.bmp", "0" * 64, 1, 1)
    base = CoordinateActionContext(
        display=backend.display,
        window=session.window,
        target=DesktopRect(10, 10, 20, 20),
        focused=False,
        before_artifact=before,
        interrupt_enabled=True,
    )
    with pytest.raises(WindowsDesktopError, match="focus"):
        session.coordinate_fallback(base, verifier=lambda: True)


@pytest.mark.skipif(os.name != "nt", reason="native Win32 synthetic smoke")
def test_native_synthetic_desktop_semantics_and_screenshot(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "phase5_desktop_app.py"
    events = []
    session = WindowsDesktopSession(
        backend=Win32SemanticBackend(),
        artifact_root=tmp_path / "artifacts",
        event_sink=lambda name, payload: events.append((name, payload)),
    )
    try:
        window = session.start_test_application(
            executable=getattr(sys, "_base_executable", sys.executable),
            script=fixture,
            expected_title="OpenJarvis Phase 5 Synthetic Desktop",
            allowed_root=fixture.parent,
        )
        assert session.backend.is_owned_process(window.process_id, session.process.pid)
        edit = session.element(automation_id=1001, role="edit")
        button = session.element(automation_id=1002, role="button")
        status = session.element(automation_id=1003, role="static")
        assert session.set_text(edit, "Fake Desktop User") == "Fake Desktop User"
        session.click(
            button,
            verifier=lambda: (
                session.element(automation_id=1003, role="static").name
                == "Verified: clicked"
            ),
        )
        assert session.element(automation_id=1003, role="static").name != status.name
        screenshot = session.screenshot()
        assert Path(screenshot.path).read_bytes().startswith(b"BM")
        assert any(name == "desktop.action_verified" for name, _ in events)
    finally:
        session.close()
