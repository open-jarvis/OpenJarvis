"""Tests for the app_launcher tool."""

from __future__ import annotations

import openjarvis.tools.app_launcher as app_launcher
from openjarvis.tools.app_launcher import (
    AppEntry,
    AppLauncherTool,
    find_app,
    is_default_browser_query,
)


def _entries(*pairs):
    return [AppEntry(name=name, path=path, source="test") for name, path in pairs]


class TestNormalizeAndAliases:
    def test_default_browser_terms_recognized(self):
        assert is_default_browser_query("navegador") is True
        assert is_default_browser_query("browser") is True
        assert is_default_browser_query("Navegador Padrão") is True
        assert is_default_browser_query("chrome") is False


class TestFindApp:
    def test_exact_match(self):
        candidates = _entries(
            ("Chrome", "C:/chrome.exe"), ("Discord", "C:/discord.exe")
        )
        outcome = find_app("Chrome", candidates)
        assert outcome.status == "found"
        assert outcome.match.name == "Chrome"

    def test_no_candidates_not_found(self):
        outcome = find_app("Chrome", [])
        assert outcome.status == "not_found"

    def test_no_match_not_found(self):
        candidates = _entries(("Discord", "C:/discord.exe"))
        outcome = find_app("Photoshop", candidates)
        assert outcome.status == "not_found"

    def test_ambiguous_close_matches(self):
        candidates = _entries(
            ("Google Chrome", "C:/chrome.exe"),
            ("Google Chrome Canary", "C:/chrome_canary.exe"),
        )
        outcome = find_app("chrome", candidates)
        assert outcome.status == "ambiguous"
        names = {c.name for c in outcome.candidates}
        assert "Google Chrome" in names
        assert "Google Chrome Canary" in names

    def test_alias_resolves_to_known_command(self):
        candidates = _entries(("calc", "C:/Windows/System32/calc.exe"))
        outcome = find_app("calculadora", candidates)
        assert outcome.status == "found"
        assert outcome.match.name == "calc"

    def test_duplicate_path_collapses_to_single_match(self):
        # Same underlying app discovered twice (e.g. App Paths + Start Menu).
        candidates = _entries(
            ("Discord", "C:/discord.exe"), ("Discord", "C:/discord.exe")
        )
        outcome = find_app("Discord", candidates)
        assert outcome.status == "found"


class TestAppLauncherToolOpen:
    def test_open_missing_app_name(self):
        tool = AppLauncherTool()
        result = tool.execute(action="open", app_name="")
        assert result.success is False

    def test_open_unknown_action(self):
        tool = AppLauncherTool()
        result = tool.execute(action="frobnicate", app_name="Chrome")
        assert result.success is False

    def test_open_found_launches(self, monkeypatch):
        candidates = _entries(("Chrome", "C:/chrome.exe"))
        monkeypatch.setattr(app_launcher, "discover_apps", lambda: candidates)
        monkeypatch.setattr(app_launcher, "_executable_exists", lambda p: True)
        launched = {}

        def fake_launch(path):
            launched["path"] = path
            return True, ""

        monkeypatch.setattr(app_launcher, "_launch_path", fake_launch)

        tool = AppLauncherTool()
        result = tool.execute(action="open", app_name="Chrome")
        assert result.success is True
        assert "Chrome" in result.content
        assert launched["path"] == "C:/chrome.exe"

    def test_open_not_found_warns_clearly(self, monkeypatch):
        monkeypatch.setattr(app_launcher, "discover_apps", lambda: [])
        tool = AppLauncherTool()
        result = tool.execute(action="open", app_name="Photoshop")
        assert result.success is False
        assert "Photoshop" in result.content
        assert "não encontrei" in result.content.lower()

    def test_open_ambiguous_asks_which_one(self, monkeypatch):
        candidates = _entries(
            ("Google Chrome", "C:/chrome.exe"),
            ("Google Chrome Canary", "C:/chrome_canary.exe"),
        )
        monkeypatch.setattr(app_launcher, "discover_apps", lambda: candidates)
        tool = AppLauncherTool()
        result = tool.execute(action="open", app_name="chrome")
        assert result.success is False
        assert result.metadata.get("ambiguous") is True
        assert "Google Chrome" in result.content
        assert "Google Chrome Canary" in result.content

    def test_open_missing_executable_reports_clearly(self, monkeypatch):
        candidates = _entries(("Uninstalled App", "C:/nowhere/app.exe"))
        monkeypatch.setattr(app_launcher, "discover_apps", lambda: candidates)
        monkeypatch.setattr(app_launcher, "_executable_exists", lambda p: False)
        tool = AppLauncherTool()
        result = tool.execute(action="open", app_name="Uninstalled App")
        assert result.success is False
        assert "desinstalado" in result.content.lower()

    def test_open_launch_failure_surfaces_error(self, monkeypatch):
        candidates = _entries(("Chrome", "C:/chrome.exe"))
        monkeypatch.setattr(app_launcher, "discover_apps", lambda: candidates)
        monkeypatch.setattr(app_launcher, "_executable_exists", lambda p: True)
        monkeypatch.setattr(
            app_launcher, "_launch_path", lambda path: (False, "access denied")
        )
        tool = AppLauncherTool()
        result = tool.execute(action="open", app_name="Chrome")
        assert result.success is False
        assert "access denied" in result.content

    def test_open_default_browser(self, monkeypatch):
        monkeypatch.setattr(app_launcher, "_launch_default_browser", lambda: (True, ""))
        tool = AppLauncherTool()
        result = tool.execute(action="open", app_name="navegador")
        assert result.success is True
        assert result.metadata["app"] == "default_browser"

    def test_open_never_receives_raw_path_parameter(self):
        # The tool's spec only exposes app_name/action — no raw path param
        # a caller could use to bypass discovery.
        tool = AppLauncherTool()
        assert set(tool.spec.parameters["properties"].keys()) == {"action", "app_name"}


class TestAppLauncherToolClose:
    def test_close_found_terminates(self, monkeypatch):
        running = _entries(("Spotify", "1234"))
        monkeypatch.setattr(app_launcher, "_list_running_processes", lambda: running)
        terminated = {}

        def fake_terminate(pid):
            terminated["pid"] = pid
            return True, ""

        monkeypatch.setattr(app_launcher, "_terminate_process", fake_terminate)

        tool = AppLauncherTool()
        result = tool.execute(action="close", app_name="Spotify")
        assert result.success is True
        assert terminated["pid"] == 1234

    def test_close_not_running(self, monkeypatch):
        monkeypatch.setattr(
            app_launcher, "_list_running_processes", lambda: _entries(("Discord", "1"))
        )
        tool = AppLauncherTool()
        result = tool.execute(action="close", app_name="Spotify")
        assert result.success is False
        assert "não parece estar em execução" in result.content

    def test_close_ambiguous(self, monkeypatch):
        running = _entries(("Google Chrome", "111"), ("Google Chrome Canary", "222"))
        monkeypatch.setattr(app_launcher, "_list_running_processes", lambda: running)
        tool = AppLauncherTool()
        result = tool.execute(action="close", app_name="chrome")
        assert result.success is False
        assert result.metadata.get("ambiguous") is True

    def test_close_no_processes_listed(self, monkeypatch):
        monkeypatch.setattr(app_launcher, "_list_running_processes", lambda: [])
        tool = AppLauncherTool()
        result = tool.execute(action="close", app_name="Spotify")
        assert result.success is False


class TestAppLauncherToolSpec:
    def test_spec_requires_code_execute_capability(self):
        tool = AppLauncherTool()
        assert "code:execute" in tool.spec.required_capabilities

    def test_spec_name_and_category(self):
        tool = AppLauncherTool()
        assert tool.spec.name == "app_launcher"
        assert tool.spec.category == "system"
