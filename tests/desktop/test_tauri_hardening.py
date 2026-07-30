"""Static regression tests for the bounded Phase 6 desktop surface."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tauri_capabilities_do_not_expose_shell_or_broad_process() -> None:
    capability = json.loads(
        (ROOT / "frontend/src-tauri/capabilities/default.json").read_text(
            encoding="utf-8"
        )
    )
    permissions = capability["permissions"]
    assert "process:default" not in permissions
    assert not any(
        isinstance(item, str) and item.startswith("shell:") for item in permissions
    )
    assert "process:allow-restart" in permissions


def test_arbitrary_jarvis_command_is_not_registered() -> None:
    source = (ROOT / "frontend/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    handler = source.split("tauri::generate_handler![", 1)[1].split("]", 1)[0]
    assert "run_jarvis_command" not in handler
    assert ".plugin(tauri_plugin_shell::init())" not in source


def test_desktop_close_dialog_offers_explicit_task_choices() -> None:
    source = (ROOT / "frontend/src/pages/JarvisPage.tsx").read_text(encoding="utf-8")
    for label in (
        "Continue in background",
        "Pause active task, then hide",
        "Cancel active task, then hide",
        "Keep window open",
    ):
        assert label in source
    assert 'role="dialog"' in source
    assert 'aria-modal="true"' in source
