"""Tests for `jarvis desktop` — the native-window launcher.

Actually opening a pywebview window needs a real display and isn't
exercised here (that was verified manually, live, against this machine —
see the PR description); these tests cover the parts that don't require a
GUI: icon resolution, health polling, and subprocess cleanup.
"""

from __future__ import annotations

import subprocess
import sys

import requests
from click.testing import CliRunner

import openjarvis.cli.desktop_cmd as desktop_cmd
from openjarvis.cli.desktop_cmd import _resolve_icon, _stop_server, _wait_until_healthy


class TestResolveIcon:
    def test_returns_none_for_missing_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(desktop_cmd, "_ICON_PATH", tmp_path / "does-not-exist.ico")
        assert _resolve_icon() is None

    def test_returns_path_string_when_present(self, tmp_path):
        icon = tmp_path / "icon.ico"
        icon.write_bytes(b"\x00")
        original = desktop_cmd._ICON_PATH
        desktop_cmd._ICON_PATH = icon
        try:
            result = _resolve_icon()
            assert result == str(icon)
        finally:
            desktop_cmd._ICON_PATH = original


class TestWaitUntilHealthy:
    def test_true_on_200(self, monkeypatch):
        class FakeResponse:
            status_code = 200

        monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
        assert _wait_until_healthy("http://127.0.0.1:9", timeout_s=2) is True

    def test_false_when_never_reachable(self, monkeypatch):
        def raising_get(*args, **kwargs):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(requests, "get", raising_get)
        monkeypatch.setattr(desktop_cmd, "_POLL_INTERVAL_S", 0.05)
        assert _wait_until_healthy("http://127.0.0.1:9", timeout_s=0.1) is False

    def test_false_on_non_200(self, monkeypatch):
        class FakeResponse:
            status_code = 503

        monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
        monkeypatch.setattr(desktop_cmd, "_POLL_INTERVAL_S", 0.05)
        assert _wait_until_healthy("http://127.0.0.1:9", timeout_s=0.1) is False


class TestStopServer:
    def test_terminates_running_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert proc.poll() is None
        _stop_server(proc, timeout_s=5)
        assert proc.poll() is not None

    def test_noop_on_already_exited_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=5)
        # Must not raise even though the process is already gone.
        _stop_server(proc, timeout_s=2)
        assert proc.poll() is not None


class TestDesktopCommand:
    def test_help(self):
        from openjarvis.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["desktop", "--help"])
        assert result.exit_code == 0
        assert "native app window" in result.output.lower()

    def test_exits_nonzero_when_backend_never_becomes_healthy(self, monkeypatch):
        from openjarvis.cli import cli

        fake_proc = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        fake_proc.wait(timeout=5)

        monkeypatch.setattr(desktop_cmd, "_start_server", lambda host, port: fake_proc)
        monkeypatch.setattr(
            desktop_cmd, "_wait_until_healthy", lambda url, timeout_s: False
        )
        monkeypatch.setattr(desktop_cmd, "_STARTUP_TIMEOUT_S", 0.1)

        runner = CliRunner()
        result = runner.invoke(cli, ["desktop"])
        assert result.exit_code != 0
        assert "did not become healthy" in result.output.lower()
