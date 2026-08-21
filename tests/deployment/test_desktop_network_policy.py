"""Regression guards for the desktop app's outbound network policy."""

from __future__ import annotations

import json
import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TAURI_CONFIG = ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
MACOS_INFO_PLIST = ROOT / "frontend" / "src-tauri" / "Info.plist"
DESKTOP_WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"


def _csp_sources(directive: str) -> set[str]:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    csp = config["app"]["security"]["csp"]
    directives = {
        parts[0]: set(parts[1:]) for item in csp.split(";") if (parts := item.split())
    }
    return directives[directive]


def test_desktop_csp_allows_remote_api_servers() -> None:
    """The user-configured API URL may point beyond localhost (#649)."""
    connect_sources = _csp_sources("connect-src")

    assert {"http:", "https:", "ws:", "wss:"} <= connect_sources


def test_macos_webview_allows_user_configured_http_servers() -> None:
    """CSP alone cannot override App Transport Security for public hosts."""
    info = plistlib.loads(MACOS_INFO_PLIST.read_bytes())

    assert info["NSAppTransportSecurity"]["NSAllowsArbitraryLoadsInWebContent"] is True


def test_local_build_does_not_require_updater_signing_key() -> None:
    """Updater artifacts are a release concern, not a local-build default."""
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))

    assert config["bundle"]["createUpdaterArtifacts"] is False


def test_release_workflow_explicitly_enables_updater_artifacts() -> None:
    """Signed releases must still publish updater signatures and latest.json."""
    workflow = DESKTOP_WORKFLOW.read_text(encoding="utf-8")

    assert '"createUpdaterArtifacts":true' in workflow
    assert "uploadUpdaterJson: true" in workflow
